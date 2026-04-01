/* j2 (SuperH-2) MOV.B store instruction tests */
/* MOV.B Rm, @Rn stores 8-bit value to memory */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Store byte tests
   *-------------------------------------------------------------*/

  /* Test basic mov.b store */
  TEST_CASE( 2, r3, 0x00000012, \
    mov #0x12, r1; \
    mova test_2_mem, r0; \
    mov.b r1, @r0; \
    mov.b @r0, r3; \
    bra 3f; \
    nop; \
    .align 2; \
  test_2_mem: \
    .long 0; \
  3: \
  )

  /* Test mov.b store truncates upper bits */
  TEST_CASE( 3, r3, 0x00000078, \
    mov.l test_3_val, r1; \
    mova test_3_mem, r0; \
    mov.b r1, @r0; \
    mov.b @r0, r3; \
    bra 3f; \
    nop; \
    .align 2; \
  test_3_val: \
    .long 0x12345678; \
  test_3_mem: \
    .long 0; \
  3: \
  )

  /* Test mov.b store and sign extend load */
  TEST_CASE( 4, r3, 0xffffff80, \
    mov #0x80, r1; \
    mova test_4_mem, r0; \
    mov.b r1, @r0; \
    mov.b @r0, r3; \
    bra 3f; \
    nop; \
    .align 2; \
  test_4_mem: \
    .long 0; \
  3: \
  )

  /* Test mov.b store zero */
  TEST_CASE( 5, r3, 0x00000000, \
    mov #0, r1; \
    mova test_5_mem, r0; \
    mov.b r1, @r0; \
    mov.b @r0, r3; \
    bra 3f; \
    nop; \
    .align 2; \
  test_5_mem: \
    .long 0x000000ff; \
  3: \
  )

  /* Test mov.b store 0xff */
  TEST_CASE( 6, r3, 0xffffffff, \
    mov #0xff, r1; \
    mova test_6_mem, r0; \
    mov.b r1, @r0; \
    mov.b @r0, r3; \
    bra 3f; \
    nop; \
    .align 2; \
  test_6_mem: \
    .long 0; \
  3: \
  )

  /* Test mov.b store 0x7f */
  TEST_CASE( 7, r3, 0x0000007f, \
    mov #0x7f, r1; \
    mova test_7_mem, r0; \
    mov.b r1, @r0; \
    mov.b @r0, r3; \
    bra 3f; \
    nop; \
    .align 2; \
  test_7_mem: \
    .long 0; \
  3: \
  )

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
