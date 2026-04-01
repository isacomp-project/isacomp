/* SPARCv8 FBLE instruction test (FP Branch Less or Equal) */

#include "test_macros.h"

SPARCV8_TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * FBLE (FP Branch if Less or Equal) tests
   * FBLE branches if fcc = less or fcc = equal
   *-------------------------------------------------------------*/

  /*-------------------------------------------------------------
   * Test 2: FBLE taken (1.0 < 2.0)
   *-------------------------------------------------------------*/
test_2:
    mov 2, TESTNUM
    set float_one, %l1
    ld [%l1], %f0
    set float_two, %l2
    ld [%l2], %f1
    fcmps %f0, %f1        /* 1.0 < 2.0 */
    fble test_2_target    /* Should branch (less) */
    nop
    ba fail
    nop
test_2_target:
    ba test_2_pass
    nop
test_2_pass:

  /*-------------------------------------------------------------
   * Test 3: FBLE taken (equal: 2.0 == 2.0)
   *-------------------------------------------------------------*/
test_3:
    mov 3, TESTNUM
    set float_two, %l1
    ld [%l1], %f0
    ld [%l1], %f1
    fcmps %f0, %f1        /* 2.0 == 2.0 */
    fble test_3_target    /* Should branch (equal) */
    nop
    ba fail
    nop
test_3_target:
    ba test_3_pass
    nop
test_3_pass:

  /*-------------------------------------------------------------
   * Test 4: FBLE not taken (3.0 > 2.0)
   *-------------------------------------------------------------*/
test_4:
    mov 4, TESTNUM
    set float_three, %l1
    ld [%l1], %f0
    set float_two, %l2
    ld [%l2], %f1
    fcmps %f0, %f1        /* 3.0 > 2.0 */
    fble test_4_fail      /* Should NOT branch */
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
