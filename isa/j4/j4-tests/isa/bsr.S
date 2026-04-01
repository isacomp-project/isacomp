/* j2 (SuperH-2) BSR instruction tests */
/* BSR branches to subroutine, saving return address in PR */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Branch to subroutine tests
   *-------------------------------------------------------------*/

  /* Test basic bsr and rts */
  TEST_CASE( 2, r2, 0x00000005, \
    mov #0, r2; \
    bsr test_2_sub; \
    nop; \
    bra test_2_done; \
    nop; \
  test_2_sub: \
    mov #5, r2; \
    rts; \
    nop; \
  test_2_done: \
    nop; \
  )

  /* Test bsr with delay slot */
  TEST_CASE( 3, r3, 0x0000000a, \
    mov #10, r3; \
    bsr test_3_sub; \
    nop; \
    bra test_3_done; \
    nop; \
  test_3_sub: \
    rts; \
    nop; \
  test_3_done: \
    nop; \
  )

  /* Test nested bsr */
  TEST_CASE( 4, r2, 0x00000003, \
    mov #0, r2; \
    bsr test_4_sub1; \
    nop; \
    bra test_4_done; \
    nop; \
  test_4_sub1: \
    sts pr, r4; \
    bsr test_4_sub2; \
    nop; \
    lds r4, pr; \
    rts; \
    nop; \
  test_4_sub2: \
    mov #3, r2; \
    rts; \
    nop; \
  test_4_done: \
    nop; \
  )

  /* Test bsr return value */
  TEST_CASE( 5, r2, 0x00000007, \
    bsr test_5_sub; \
    nop; \
    mov r1, r2; \
    bra test_5_done; \
    nop; \
  test_5_sub: \
    mov #7, r1; \
    rts; \
    nop; \
  test_5_done: \
    nop; \
  )

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
