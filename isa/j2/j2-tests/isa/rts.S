/* j2 (SuperH-2) RTS instruction tests */
/* RTS returns from subroutine using PR register */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Return from subroutine tests
   *-------------------------------------------------------------*/

  /* Test basic rts */
  TEST_CASE( 2, r2, 0x00000005, \
    bsr test_2_sub; \
    nop; \
    mov r1, r2; \
    bra test_2_done; \
    nop; \
  test_2_sub: \
    mov #5, r1; \
    rts; \
    nop; \
  test_2_done: \
    nop; \
  )

  /* Test rts with delay slot */
  TEST_CASE( 3, r2, 0x0000000a, \
    bsr test_3_sub; \
    nop; \
    mov r1, r2; \
    bra test_3_done; \
    nop; \
  test_3_sub: \
    rts; \
    mov #10, r1; \
  test_3_done: \
    nop; \
  )

  /* Test rts returns to correct location */
  TEST_CASE( 4, r3, 0x00000007, \
    bsr test_4_sub; \
    nop; \
    mov #7, r3; \
    bra test_4_done; \
    nop; \
  test_4_sub: \
    mov #0, r3; \
    rts; \
    nop; \
  test_4_done: \
    nop; \
  )

  /* Test multiple rts in nested calls */
  TEST_CASE( 5, r2, 0x00000003, \
    bsr test_5_sub1; \
    nop; \
    mov r1, r2; \
    bra test_5_done; \
    nop; \
  test_5_sub1: \
    sts pr, r4; \
    bsr test_5_sub2; \
    nop; \
    lds r4, pr; \
    rts; \
    nop; \
  test_5_sub2: \
    mov #3, r1; \
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
