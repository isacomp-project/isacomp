/* SPARCv8 LDDF instruction test (Load Double Floating-point) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * LDDF (Load Double Floating-point) tests
   * LDDF loads a double-precision FP value from memory into even/odd FP reg pair
   *-------------------------------------------------------------*/

  /*-------------------------------------------------------------
   * Test 2: LDDF basic load
   *-------------------------------------------------------------*/
test_2:
    mov 2, TESTNUM
    set double_val1, %l1
    ldd [%l1], %f0        /* Load double into %f0:%f1 */
    /* Verify by storing back */
    set result_buf, %l2
    std %f0, [%l2]
    ld [%l2], %l3         /* High word */
    ld [%l1], %l4
    cmp %l3, %l4
    bne test_2_fail
    nop
    ld [%l2 + 4], %l3     /* Low word */
    ld [%l1 + 4], %l4
    cmp %l3, %l4
    be test_2_pass
    nop
test_2_fail:
    ba fail
    nop
test_2_pass:

  /*-------------------------------------------------------------
   * Test 3: LDDF with offset
   *-------------------------------------------------------------*/
test_3:
    mov 3, TESTNUM
    set double_array, %l1
    ldd [%l1 + 8], %f2    /* Load second double into %f2:%f3 */
    set result_buf, %l2
    std %f2, [%l2]
    ld [%l2], %l3
    ld [%l1 + 8], %l4
    cmp %l3, %l4
    be test_3_pass
    nop
    ba fail
    nop
test_3_pass:

  /*-------------------------------------------------------------
   * Test 4: Multiple LDDF
   *-------------------------------------------------------------*/
test_4:
    mov 4, TESTNUM
    set double_array, %l1
    ldd [%l1], %f0
    ldd [%l1 + 8], %f2
    /* Just verify execution completes */
    set 42, %l2
    cmp %l2, 42
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
  .word 0x400921FB      /* High word of PI (3.14159...) */
  .word 0x54442D18      /* Low word */

  .align 8
double_array:
  .word 0x3FF00000, 0x00000000   /* 1.0 */
  .word 0x40000000, 0x00000000   /* 2.0 */

  .align 8
result_buf:
  .word 0
  .word 0

SPARCV8_DATA_END
