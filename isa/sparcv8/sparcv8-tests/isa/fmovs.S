/* SPARCv8 FMOVS instruction test (Floating-point Move Single) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * FMOVS (FP Move Single) tests
   * FMOVS copies a single-precision FP register to another
   *-------------------------------------------------------------*/

  /*-------------------------------------------------------------
   * Test 2: FMOVS basic move
   *-------------------------------------------------------------*/
test_2:
    mov 2, TESTNUM
    set float_val, %l1
    ld [%l1], %f0         /* f0 = test value */
    fmovs %f0, %f1        /* f1 = f0 */
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
   * Test 3: FMOVS to different register
   *-------------------------------------------------------------*/
test_3:
    mov 3, TESTNUM
    set float_pi, %l1
    ld [%l1], %f4         /* f4 = PI */
    fmovs %f4, %f7        /* f7 = f4 */
    set result_buf, %l2
    st %f7, [%l2]
    ld [%l2], %l3
    ld [%l1], %l4
    cmp %l3, %l4
    be test_3_pass
    nop
    ba fail
    nop
test_3_pass:

  /*-------------------------------------------------------------
   * Test 4: FMOVS preserves source
   *-------------------------------------------------------------*/
test_4:
    mov 4, TESTNUM
    set float_val, %l1
    ld [%l1], %f0
    fmovs %f0, %f1
    /* Check source is unchanged */
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
float_val:
  .word 0x40490FDB      /* PI = 3.14159... */
float_pi:
  .word 0x40490FDB      /* PI = 3.14159... */

  .align 4
result_buf:
  .word 0

SPARCV8_DATA_END
