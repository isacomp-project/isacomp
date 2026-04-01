/* j2 (SuperH-2) BRAF instruction tests */
/* BRAF branches to PC + 4 + Rn with delay slot */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Branch tests - Branch far (PC-relative via register)
   *-------------------------------------------------------------*/

  /* Test basic braf with offset 0 */
  TEST_CASE( 2, r2, 0x00000001, \
    mov #0, r1; \
    mov #1, r2; \
    braf r1; \
    nop; \
  )

  /* Test braf with positive offset */
  TEST_CASE( 3, r3, 0x00000005, \
    mova test_3_offset, r0; \
    mov.l @r0, r1; \
    mov #5, r3; \
  braf_3: \
    braf r1; \
    nop; \
    mov #0, r3; \
    mov #0, r3; \
    bra test_3_done; \
    nop; \
    .align 2; \
  test_3_offset: \
    .long test_3_done - braf_3 - 4; \
  test_3_done: \
    nop; \
  )

  /* Test braf with delay slot */
  TEST_CASE( 4, r2, 0x0000000a, \
    mov #0, r1; \
    mov #0, r2; \
    braf r1; \
    mov #10, r2; \
  )

  /* Test braf skipping instructions */
  TEST_CASE( 5, r2, 0x00000007, \
    mova test_5_offset, r0; \
    mov.l @r0, r1; \
    mov #7, r2; \
  braf_5: \
    braf r1; \
    nop; \
    mov #0, r2; \
    mov #0, r2; \
    bra test_5_done; \
    nop; \
    .align 2; \
  test_5_offset: \
    .long test_5_done - braf_5 - 4; \
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
