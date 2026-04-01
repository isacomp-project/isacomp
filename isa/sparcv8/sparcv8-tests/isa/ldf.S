/* SPARCv8 LDF instruction test (Load Floating-point) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * LDF (Load Floating-point) tests
   * LDF loads a single-precision FP value from memory into a FP reg
   *-------------------------------------------------------------*/

  /*-------------------------------------------------------------
   * Test 2: LDF basic load
   *-------------------------------------------------------------*/
test_2:
    mov 2, TESTNUM
    set float_val1, %l1
    ld [%l1], %f0         /* Load FP value into %f0 */
    /* Verify by storing back and comparing */
    set result_buf, %l2
    st %f0, [%l2]
    ld [%l2], %l3
    ld [%l1], %l4
    cmp %l3, %l4
    be test_2_pass
    nop
    ba fail
    nop
test_2_pass:

  /*-------------------------------------------------------------
   * Test 3: LDF with offset
   *-------------------------------------------------------------*/
test_3:
    mov 3, TESTNUM
    set float_array, %l1
    ld [%l1 + 4], %f1     /* Load second float in array */
    set result_buf, %l2
    st %f1, [%l2]
    ld [%l2], %l3
    set float_array, %l4
    ld [%l4 + 4], %l5
    cmp %l3, %l5
    be test_3_pass
    nop
    ba fail
    nop
test_3_pass:

  /*-------------------------------------------------------------
   * Test 4: Multiple LDF
   *-------------------------------------------------------------*/
test_4:
    mov 4, TESTNUM
    set float_array, %l1
    ld [%l1], %f0
    ld [%l1 + 4], %f1
    ld [%l1 + 8], %f2
    /* Verify first load */
    set result_buf, %l2
    st %f0, [%l2]
    ld [%l2], %l3
    ld [%l1], %l4
    cmp %l3, %l4
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
float_val1:
  .word 0x40490FDB      /* Approx PI = 3.14159... */

  .align 4
float_array:
  .word 0x3F800000      /* 1.0f */
  .word 0x40000000      /* 2.0f */
  .word 0x40400000      /* 3.0f */

  .align 4
result_buf:
  .word 0

SPARCV8_DATA_END
