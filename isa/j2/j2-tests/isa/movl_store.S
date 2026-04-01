/* j2 (SuperH-2) MOV.L store instruction tests */
/* MOV.L Rm, @Rn stores 32-bit value to memory */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Store long tests
   *-------------------------------------------------------------*/

  /* Test basic mov.l store */
  TEST_CASE( 2, r3, 0x12345678, \
    mov.l test_2_val, r1; \
    mova test_2_mem, r0; \
    mov.l r1, @r0; \
    mov.l @r0, r3; \
    bra 3f; \
    nop; \
    .align 2; \
  test_2_val: \
    .long 0x12345678; \
  test_2_mem: \
    .long 0; \
  3: \
  )

  /* Test mov.l store zero */
  TEST_CASE( 3, r3, 0x00000000, \
    mov #0, r1; \
    mova test_3_mem, r0; \
    mov.l r1, @r0; \
    mov.l @r0, r3; \
    bra 3f; \
    nop; \
    .align 2; \
  test_3_mem: \
    .long 0xffffffff; \
  3: \
  )

  /* Test mov.l store -1 */
  TEST_CASE( 4, r3, 0xffffffff, \
    mov #-1, r1; \
    mova test_4_mem, r0; \
    mov.l r1, @r0; \
    mov.l @r0, r3; \
    bra 3f; \
    nop; \
    .align 2; \
  test_4_mem: \
    .long 0; \
  3: \
  )

  /* Test mov.l store and load back */
  TEST_CASE( 5, r4, 0xabcdef00, \
    mov.l test_5_val, r2; \
    mova test_5_mem, r0; \
    mov.l r2, @r0; \
    mov.l @r0, r4; \
    bra 3f; \
    nop; \
    .align 2; \
  test_5_val: \
    .long 0xabcdef00; \
  test_5_mem: \
    .long 0; \
  3: \
  )

  /* Test multiple mov.l stores */
  TEST_CASE( 6, r5, 0x77777777, \
    mov.l test_6_val1, r1; \
    mov.l test_6_val2, r2; \
    mova test_6_mem, r0; \
    mov.l r1, @r0; \
    add #4, r0; \
    mov.l r2, @r0; \
    mov.l @r0, r5; \
    bra 3f; \
    nop; \
    .align 2; \
  test_6_val1: \
    .long 0x11111111; \
  test_6_val2: \
    .long 0x77777777; \
  test_6_mem: \
    .long 0, 0; \
  3: \
  )

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
