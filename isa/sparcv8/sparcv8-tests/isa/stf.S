/* SPARCv8 STF instruction test (Store Floating-point) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * STF (Store Floating-point) tests
   * STF stores a single-precision FP value from a FP reg to memory
   *-------------------------------------------------------------*/

  /*-------------------------------------------------------------
   * Test 2: STF basic store
   *-------------------------------------------------------------*/
test_2:
    mov 2, TESTNUM
    set float_val1, %l1
    ld [%l1], %f0         /* Load a known value */
    set store_buf1, %l2
    st %f0, [%l2]         /* Store it */
    ld [%l2], %l3         /* Read back as integer */
    ld [%l1], %l4         /* Original value */
    cmp %l3, %l4
    be test_2_pass
    nop
    ba fail
    nop
test_2_pass:

  /*-------------------------------------------------------------
   * Test 3: STF with offset
   *-------------------------------------------------------------*/
test_3:
    mov 3, TESTNUM
    set float_val2, %l1
    ld [%l1], %f1
    set store_array, %l2
    st %f1, [%l2 + 4]     /* Store to second position */
    ld [%l2 + 4], %l3
    ld [%l1], %l4
    cmp %l3, %l4
    be test_3_pass
    nop
    ba fail
    nop
test_3_pass:

  /*-------------------------------------------------------------
   * Test 4: Multiple STF
   *-------------------------------------------------------------*/
test_4:
    mov 4, TESTNUM
    set float_array, %l1
    ld [%l1], %f0
    ld [%l1 + 4], %f1
    ld [%l1 + 8], %f2
    set store_array, %l2
    st %f0, [%l2]
    st %f1, [%l2 + 4]
    st %f2, [%l2 + 8]
    /* Verify third store */
    ld [%l2 + 8], %l3
    ld [%l1 + 8], %l4
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
  .word 0x40490FDB      /* Approx PI */

float_val2:
  .word 0x402DF854      /* Approx E = 2.718... */

  .align 4
float_array:
  .word 0x3F800000      /* 1.0f */
  .word 0x40000000      /* 2.0f */
  .word 0x40400000      /* 3.0f */

  .align 4
store_buf1:
  .word 0

  .align 4
store_array:
  .word 0
  .word 0
  .word 0

SPARCV8_DATA_END
