/* j2 (SuperH-2) MOV.W store instruction tests */
/* MOV.W Rm, @Rn stores 16-bit value to memory */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Store word tests
   *-------------------------------------------------------------*/

  /* Test basic mov.w store */
  TEST_CASE( 2, r3, 0x00001234, \
    mov.l test_2_val, r1; \
    mova test_2_mem, r0; \
    mov.w r1, @r0; \
    mov.w @r0, r3; \
    bra 3f; \
    nop; \
    .align 2; \
  test_2_val: \
    .long 0x00001234; \
  test_2_mem: \
    .word 0; \
  3: \
  )

  /* Test mov.w store truncates upper bits */
  TEST_CASE( 3, r3, 0x00005678, \
    mov.l test_3_val, r1; \
    mova test_3_mem, r0; \
    mov.w r1, @r0; \
    mov.w @r0, r3; \
    bra 3f; \
    nop; \
    .align 2; \
  test_3_val: \
    .long 0x12345678; \
  test_3_mem: \
    .word 0; \
  3: \
  )

  /* Test mov.w store and sign extend load */
  TEST_CASE( 4, r3, 0xffff8000, \
    mov.l test_4_val, r1; \
    mova test_4_mem, r0; \
    mov.w r1, @r0; \
    mov.w @r0, r3; \
    bra 3f; \
    nop; \
    .align 2; \
  test_4_val: \
    .long 0x00008000; \
  test_4_mem: \
    .word 0; \
  3: \
  )

  /* Test mov.w store zero */
  TEST_CASE( 5, r3, 0x00000000, \
    mov #0, r1; \
    mova test_5_mem, r0; \
    mov.w r1, @r0; \
    mov.w @r0, r3; \
    bra 3f; \
    nop; \
    .align 2; \
  test_5_mem: \
    .word 0xffff; \
  3: \
  )

  /* Test mov.w store 0xffff */
  TEST_CASE( 6, r3, 0xffffffff, \
    mov #-1, r1; \
    mova test_6_mem, r0; \
    mov.w r1, @r0; \
    mov.w @r0, r3; \
    bra 3f; \
    nop; \
    .align 2; \
  test_6_mem: \
    .word 0; \
  3: \
  )

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
