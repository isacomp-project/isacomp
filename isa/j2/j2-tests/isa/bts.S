/* j2 (SuperH-2) BT/S instruction tests */
/* BT/S branches if T=1 with delay slot */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Conditional branch tests - BT/S (branch if true with delay)
   *-------------------------------------------------------------*/

  /* Test bt/s when T=1 (branch taken) */
  TEST_CASE( 2, r2, 0x00000005, \
    sett; \
    mov #5, r2; \
    bt/s test_2_target; \
    nop; \
    mov #0, r2; \
  test_2_target: \
    nop; \
  )

  /* Test bt/s when T=0 (branch not taken) */
  TEST_CASE( 3, r2, 0x00000003, \
    clrt; \
    mov #3, r2; \
    bt/s test_3_target; \
    nop; \
    bra test_3_done; \
    nop; \
  test_3_target: \
    mov #0, r2; \
  test_3_done: \
    nop; \
  )

  /* Test bt/s with delay slot execution when taken */
  TEST_CASE( 4, r3, 0x0000000a, \
    sett; \
    mov #0, r3; \
    bt/s test_4_target; \
    mov #10, r3; \
    mov #20, r3; \
  test_4_target: \
    nop; \
  )

  /* Test bt/s with delay slot execution when not taken */
  TEST_CASE( 5, r3, 0x00000007, \
    clrt; \
    mov #0, r3; \
    bt/s test_5_target; \
    mov #7, r3; \
    bra test_5_done; \
    nop; \
  test_5_target: \
    mov #20, r3; \
  test_5_done: \
    nop; \
  )

  /* Test bt/s with cmp/eq result */
  TEST_CASE( 6, r2, 0x00000001, \
    mov #5, r1; \
    mov #5, r3; \
    cmp/eq r1, r3; \
    bt/s test_6_target; \
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
