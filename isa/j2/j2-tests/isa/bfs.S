/* j2 (SuperH-2) BF/S instruction tests */
/* BF/S branches if T=0 with delay slot */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Conditional branch tests - BF/S (branch if false with delay)
   *-------------------------------------------------------------*/

  /* Test bf/s when T=0 (branch taken) */
  TEST_CASE( 2, r2, 0x00000005, \
    clrt; \
    mov #5, r2; \
    bf/s test_2_target; \
    nop; \
    mov #0, r2; \
  test_2_target: \
    nop; \
  )

  /* Test bf/s when T=1 (branch not taken) */
  TEST_CASE( 3, r2, 0x00000003, \
    sett; \
    mov #3, r2; \
    bf/s test_3_target; \
    nop; \
    bra test_3_done; \
    nop; \
  test_3_target: \
    mov #0, r2; \
  test_3_done: \
    nop; \
  )

  /* Test bf/s with delay slot execution when taken */
  TEST_CASE( 4, r3, 0x0000000a, \
    clrt; \
    mov #0, r3; \
    bf/s test_4_target; \
    mov #10, r3; \
    mov #20, r3; \
  test_4_target: \
    nop; \
  )

  /* Test bf/s with delay slot execution when not taken */
  TEST_CASE( 5, r3, 0x00000007, \
    sett; \
    mov #0, r3; \
    bf/s test_5_target; \
    mov #7, r3; \
    bra test_5_done; \
    nop; \
  test_5_target: \
    mov #20, r3; \
  test_5_done: \
    nop; \
  )

  /* Test bf/s with cmp/eq result */
  TEST_CASE( 6, r2, 0x00000001, \
    mov #5, r1; \
    mov #6, r3; \
    cmp/eq r1, r3; \
    bf/s test_6_target; \
    mov #1, r2; \
    mov #0, r2; \
  test_6_target: \
    nop; \
  )

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
