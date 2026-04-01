/* SPARCv8 FBE instruction test (FP Branch on Equal) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * FBE (FP Branch on Equal) tests
   * FBE branches if FP compare result is equal (fcc = 0)
   *-------------------------------------------------------------*/

  /*-------------------------------------------------------------
   * Test 2: FBE should branch when values are equal
   *-------------------------------------------------------------*/
test_2:
    mov 2, TESTNUM
    set float_two, %l1
    ld [%l1], %f0
    ld [%l1], %f1         /* Both f0 and f1 = 2.0 */
    fcmps %f0, %f1        /* Compare: 2.0 == 2.0, fcc = 0 */
    nop                   /* FP compare delay */
    fbe test_2_pass       /* Should branch */
    nop
    ba fail
    nop
test_2_pass:

  /*-------------------------------------------------------------
   * Test 3: FBE should NOT branch when values are different
   *-------------------------------------------------------------*/
test_3:
    mov 3, TESTNUM
    set float_one, %l1
    ld [%l1], %f0         /* f0 = 1.0 */
    set float_two, %l2
    ld [%l2], %f1         /* f1 = 2.0 */
    fcmps %f0, %f1        /* Compare: 1.0 != 2.0, fcc != 0 */
    nop
    fbe test_3_fail       /* Should NOT branch */
    nop
    ba test_3_pass
    nop
test_3_fail:
    ba fail
    nop
test_3_pass:

  /*-------------------------------------------------------------
   * Test 4: FBE with negative values
   *-------------------------------------------------------------*/
test_4:
    mov 4, TESTNUM
    set float_neg_one, %l1
    ld [%l1], %f0
    ld [%l1], %f1         /* Both = -1.0 */
    fcmps %f0, %f1
    nop
    fbe test_4_pass       /* Should branch (equal) */
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
float_neg_one:
  .word 0xBF800000      /* -1.0f */

SPARCV8_DATA_END
