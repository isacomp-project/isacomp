/* j2 (SuperH-2) BRA instruction tests */
/* BRA is unconditional branch with delay slot */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Branch tests - Unconditional branch
   *-------------------------------------------------------------*/

  /* Test basic bra */
  TEST_CASE( 2, r2, 0x00000001, \
    mov #0, r2; \
    bra test_2_target; \
    mov #1, r2; \
    mov #2, r2; \
  test_2_target: \
    nop; \
  )

  /* Test bra forward */
  TEST_CASE( 3, r2, 0x00000005, \
    mov #5, r2; \
    bra test_3_skip; \
    nop; \
    mov #0, r2; \
    mov #0, r2; \
  test_3_skip: \
    nop; \
  )

  /* Test bra with delay slot execution */
  TEST_CASE( 4, r3, 0x0000000a, \
    mov #0, r3; \
    bra test_4_target; \
    mov #10, r3; \
    mov #20, r3; \
  test_4_target: \
    nop; \
  )

  /* Test bra backward */
  TEST_CASE( 5, r2, 0x00000003, \
    bra test_5_enter; \
    nop; \
  test_5_loop: \
    mov #3, r2; \
    bra test_5_done; \
    nop; \
  test_5_enter: \
    mov #0, r2; \
    bra test_5_loop; \
    nop; \
  test_5_done: \
    nop; \
  )

  /* Test multiple bra */
  TEST_CASE( 6, r2, 0x00000007, \
    bra test_6_a; \
    nop; \
  test_6_a: \
    bra test_6_b; \
    nop; \
  test_6_b: \
    mov #7, r2; \
  )

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
