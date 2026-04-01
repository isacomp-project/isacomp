/* SPARCv8 STDF instruction test (Store Double Floating-point) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * STDF (Store Double Floating-point) tests
   * STDF stores a double-precision FP value from even/odd FP reg pair to memory
   *-------------------------------------------------------------*/

  /*-------------------------------------------------------------
   * Test 2: STDF basic store
   *-------------------------------------------------------------*/
test_2:
    mov 2, TESTNUM
    set double_val1, %l1
    ldd [%l1], %f0        /* Load a known double value */
    set store_buf, %l2
    std %f0, [%l2]        /* Store it */
    /* Verify both words */
    ld [%l2], %l3
    ld [%l1], %l4
    cmp %l3, %l4
    bne test_2_fail
    nop
    ld [%l2 + 4], %l3
    ld [%l1 + 4], %l4
    cmp %l3, %l4
    be test_2_pass
    nop
test_2_fail:
    ba fail
    nop
test_2_pass:

  /*-------------------------------------------------------------
   * Test 3: STDF with offset
   *-------------------------------------------------------------*/
test_3:
    mov 3, TESTNUM
    set double_val2, %l1
    ldd [%l1], %f2
    set store_array, %l2
    std %f2, [%l2 + 8]    /* Store to second position */
    ld [%l2 + 8], %l3
    ld [%l1], %l4
    cmp %l3, %l4
    be test_3_pass
    nop
    ba fail
    nop
test_3_pass:

  /*-------------------------------------------------------------
   * Test 4: Multiple STDF
   *-------------------------------------------------------------*/
test_4:
    mov 4, TESTNUM
    set double_array, %l1
    ldd [%l1], %f0
    ldd [%l1 + 8], %f2
    set store_array, %l2
    std %f0, [%l2]
    std %f2, [%l2 + 8]
    /* Verify second store high word */
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

  .align 8
double_val1:
  .word 0x400921FB      /* High word of PI */
  .word 0x54442D18      /* Low word */

  .align 8
double_val2:
  .word 0x4005BF0A      /* High word of E (2.718...) */
  .word 0x8B145769      /* Low word */

  .align 8
double_array:
  .word 0x3FF00000, 0x00000000   /* 1.0 */
  .word 0x40000000, 0x00000000   /* 2.0 */

  .align 8
store_buf:
  .word 0
  .word 0

  .align 8
store_array:
  .word 0, 0
  .word 0, 0

SPARCV8_DATA_END
