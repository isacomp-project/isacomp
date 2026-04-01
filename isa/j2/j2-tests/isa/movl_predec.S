/* j2 (SuperH-2) MOV.L pre-decrement store instruction tests */
/* MOV.L Rm, @-Rn decrements Rn by 4 then stores to memory */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Store long pre-decrement tests
   *-------------------------------------------------------------*/

  /* Test basic pre-decrement store */
  TEST_CASE( 2, r3, 0x12345678, \
    mov.l test_2_val, r1; \
    mova test_2_mem, r0; \
    add #8, r0; \
    mov.l r1, @-r0; \
    mov.l @r0, r3; \
    bra 3f; \
    nop; \
    .align 2; \
  test_2_val: \
    .long 0x12345678; \
  test_2_mem: \
    .long 0, 0; \
  3: \
  )

  /* Test pre-decrement updates pointer: (base+4) - base = 4 */
  TEST_CASE( 3, r4, 0x00000004, \
    mov.l test_3_val, r1; \
    mova test_3_mem, r0; \
    add #4, r0; \
    mov r0, r2; \
    mov.l r1, @-r0; \
    sub r0, r2; \
    mov r2, r4; \
    bra 3f; \
    nop; \
    .align 2; \
  test_3_val: \
    .long 0x11111111; \
  test_3_mem: \
    .long 0, 0; \
  3: \
  )

  /* Test multiple pre-decrement stores (stack push) */
  TEST_CASE( 4, r5, 0xabcdef00, \
    mov.l test_4_val1, r1; \
    mov.l test_4_val2, r2; \
    mova test_4_mem, r0; \
    add #8, r0; \
    mov.l r1, @-r0; \
    mov.l r2, @-r0; \
    mov.l @r0, r5; \
    bra 3f; \
    nop; \
    .align 2; \
  test_4_val1: \
    .long 0x11111111; \
  test_4_val2: \
    .long 0xabcdef00; \
  test_4_mem: \
    .long 0, 0; \
  3: \
  )

  /* Test pre-decrement final value */
  TEST_CASE( 5, r3, 0x55555555, \
    mov.l test_5_val1, r1; \
    mov.l test_5_val2, r2; \
    mova test_5_mem, r0; \
    add #8, r0; \
    mov.l r1, @-r0; \
    mov.l r2, @-r0; \
    add #4, r0; \
    mov.l @r0, r3; \
    bra 3f; \
    nop; \
    .align 2; \
  test_5_val1: \
    .long 0x55555555; \
  test_5_val2: \
    .long 0x77777777; \
  test_5_mem: \
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
