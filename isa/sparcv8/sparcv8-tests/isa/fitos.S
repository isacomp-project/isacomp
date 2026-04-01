/* SPARCv8 FITOS instruction test (Convert Integer to Single FP) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * FITOS (Convert Integer to Single) tests
   * FITOS converts a 32-bit integer in an FP register to single FP
   *-------------------------------------------------------------*/

  /*-------------------------------------------------------------
   * Test 2: FITOS convert 1 to 1.0f
   *-------------------------------------------------------------*/
test_2:
    mov 2, TESTNUM
    set int_one, %l1
    ld [%l1], %f0         /* f0 = integer 1 */
    fitos %f0, %f1        /* f1 = 1.0f */
    set result_buf, %l2
    st %f1, [%l2]
    ld [%l2], %l3
    set float_one, %l4
    ld [%l4], %l5
    cmp %l3, %l5
    be test_2_pass
    nop
    ba fail
    nop
test_2_pass:

  /*-------------------------------------------------------------
   * Test 3: FITOS convert 10 to 10.0f
   *-------------------------------------------------------------*/
test_3:
    mov 3, TESTNUM
    set int_ten, %l1
    ld [%l1], %f0         /* f0 = integer 10 */
    fitos %f0, %f1        /* f1 = 10.0f */
    set result_buf, %l2
    st %f1, [%l2]
    ld [%l2], %l3
    set float_ten, %l4
    ld [%l4], %l5
    cmp %l3, %l5
    be test_3_pass
    nop
    ba fail
    nop
test_3_pass:

  /*-------------------------------------------------------------
   * Test 4: FITOS convert 0 to 0.0f
   *-------------------------------------------------------------*/
test_4:
    mov 4, TESTNUM
    set int_zero, %l1
    ld [%l1], %f0         /* f0 = integer 0 */
    fitos %f0, %f1        /* f1 = 0.0f */
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

  /*-------------------------------------------------------------
   * Test 5: FITOS convert -1 to -1.0f
   *-------------------------------------------------------------*/
test_5:
    mov 5, TESTNUM
    set int_neg_one, %l1
    ld [%l1], %f0         /* f0 = integer -1 */
    fitos %f0, %f1        /* f1 = -1.0f */
    set result_buf, %l2
    st %f1, [%l2]
    ld [%l2], %l3
    set float_neg_one, %l4
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
int_zero:
  .word 0               /* 0 */
int_one:
  .word 1               /* 1 */
int_ten:
  .word 10              /* 10 */
int_neg_one:
  .word 0xFFFFFFFF      /* -1 (two's complement) */

  .align 4
float_zero:
  .word 0x00000000      /* 0.0f */
float_one:
  .word 0x3F800000      /* 1.0f */
float_ten:
  .word 0x41200000      /* 10.0f */
float_neg_one:
  .word 0xBF800000      /* -1.0f */

  .align 4
result_buf:
  .word 0

SPARCV8_DATA_END
