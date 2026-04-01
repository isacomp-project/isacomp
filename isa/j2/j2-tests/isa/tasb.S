/* j2 (SuperH-2) TAS.B instruction tests */
/* TAS.B tests byte and sets bit 7, sets T if byte was zero */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Test and set byte tests
   *-------------------------------------------------------------*/

  /* Test tas.b with zero byte (sets T) */
  TEST_CASE( 2, r2, 0x00000001, \
    mova test_2_mem, r0; \
    tas.b @r0; \
    movt r2; \
    bra 3f; \
    nop; \
    .align 2; \
  test_2_mem: \
    .long 0; \
  3: \
  )

  /* Test tas.b with non-zero byte (clears T) */
  TEST_CASE( 3, r2, 0x00000000, \
    mova test_3_mem, r0; \
    tas.b @r0; \
    movt r2; \
    bra 3f; \
    nop; \
    .align 2; \
  test_3_mem: \
    .long 0x01000000; \
  3: \
  )

  /* Test tas.b sets bit 7: mov.b sign-extends 0x80 to 0xffffff80 */
  TEST_CASE( 4, r2, 0xffffff80, \
    mova test_4_mem, r0; \
    tas.b @r0; \
    mov.b @r0, r2; \
    bra 3f; \
    nop; \
    .align 2; \
  test_4_mem: \
    .long 0; \
  3: \
  )

  /* Test tas.b preserves bit 7 if already set */
  TEST_CASE( 5, r2, 0xffffff81, \
    mova test_5_mem, r0; \
    tas.b @r0; \
    mov.b @r0, r2; \
    bra 3f; \
    nop; \
    .align 2; \
  test_5_mem: \
    .long 0x81000000; \
  3: \
  )

  /* Test tas.b with 0x7f */
  TEST_CASE( 6, r3, 0x00000000, \
    mova test_6_mem, r0; \
    tas.b @r0; \
    movt r3; \
    mov.b @r0, r2; \
    bra 3f; \
    nop; \
    .align 2; \
  test_6_mem: \
    .long 0x7f000000; \
  3: \
  )

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
