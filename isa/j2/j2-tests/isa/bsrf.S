/* j2 (SuperH-2) BSRF instruction tests */
/* BSRF branches to subroutine at PC + 4 + Rn, saving return address in PR */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Branch to subroutine far tests
   *-------------------------------------------------------------*/

  /* Test basic bsrf and rts */
  TEST_CASE( 2, r2, 0x00000005, \
    mova test_2_offset, r0; \
    mov.l @r0, r3; \
    mov #0, r2; \
  bsrf_2: \
    bsrf r3; \
    nop; \
    bra test_2_done; \
    nop; \
    .align 2; \
  test_2_offset: \
    .long test_2_sub - bsrf_2 - 4; \
  test_2_sub: \
    mov #5, r2; \
    rts; \
    nop; \
  test_2_done: \
    nop; \
  )

  /* Test bsrf with delay slot execution */
  TEST_CASE( 3, r2, 0x0000000a, \
    mova test_3_offset, r0; \
    mov.l @r0, r3; \
  bsrf_3: \
    bsrf r3; \
    mov #10, r2; \
    bra test_3_done; \
    nop; \
    .align 2; \
  test_3_offset: \
    .long test_3_sub - bsrf_3 - 4; \
  test_3_sub: \
    rts; \
    nop; \
  test_3_done: \
    nop; \
  )

  /* Test bsrf offset calculation */
  TEST_CASE( 4, r3, 0x00000007, \
    mova test_4_offset, r0; \
    mov.l @r0, r1; \
    mov #0, r3; \
  bsrf_4: \
    bsrf r1; \
    nop; \
    bra test_4_done; \
    nop; \
    .align 2; \
  test_4_offset: \
    .long test_4_sub - bsrf_4 - 4; \
  test_4_sub: \
    mov #7, r3; \
    rts; \
    nop; \
  test_4_done: \
    nop; \
  )

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
