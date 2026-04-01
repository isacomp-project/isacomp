/* SPARCv8 FBL instruction test (FP Branch on Less) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * FBL (FP Branch on Less) tests
   * FBL branches if FP compare result is less than (fcc = 1)
   *-------------------------------------------------------------*/

  /*-------------------------------------------------------------
   * Test 2: FBL should branch when first is less
   *-------------------------------------------------------------*/
test_2:
    mov 2, TESTNUM
    set float_one, %l1
    ld [%l1], %f0         /* f0 = 1.0 */
    set float_two, %l2
    ld [%l2], %f1         /* f1 = 2.0 */
    fcmps %f0, %f1        /* Compare: 1.0 < 2.0, fcc = 1 */
    nop
    fbl test_2_pass       /* Should branch */
    nop
    ba fail
    nop
test_2_pass:

  /*-------------------------------------------------------------
   * Test 3: FBL should NOT branch when first is greater
   *-------------------------------------------------------------*/
test_3:
    mov 3, TESTNUM
    set float_three, %l1
    ld [%l1], %f0         /* f0 = 3.0 */
    set float_two, %l2
    ld [%l2], %f1         /* f1 = 2.0 */
    fcmps %f0, %f1        /* Compare: 3.0 > 2.0, fcc = 2 */
    nop
    fbl test_3_fail       /* Should NOT branch */
    nop
    ba test_3_pass
    nop
test_3_fail:
    ba fail
    nop
test_3_pass:

  /*-------------------------------------------------------------
   * Test 4: FBL should NOT branch when equal
   *-------------------------------------------------------------*/
test_4:
    mov 4, TESTNUM
    set float_two, %l1
    ld [%l1], %f0
    ld [%l1], %f1         /* Both = 2.0 */
    fcmps %f0, %f1        /* Compare: 2.0 == 2.0, fcc = 0 */
    nop
    fbl test_4_fail       /* Should NOT branch */
    nop
    ba test_4_pass
    nop
test_4_fail:
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

SPARCV8_DATA_END
