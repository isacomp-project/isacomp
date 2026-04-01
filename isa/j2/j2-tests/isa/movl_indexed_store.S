/* j2 (SuperH-2) MOV.L indexed store instruction tests */
/* MOV.L Rm, @(R0, Rn) stores to memory at Rn + R0 */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Store long indexed tests
   *-------------------------------------------------------------*/

  /* Test mov.l indexed store with offset 0 */
  TEST_CASE( 2, r4, 0x12345678, \
    mov.l test_2_val, r2; \
    mova test_2_mem, r0; \
    mov r0, r3; \
    mov #0, r0; \
    mov.l r2, @(r0, r3); \
    mov.l @r3, r4; \
    bra 3f; \
    nop; \
    .align 2; \
  test_2_val: \
    .long 0x12345678; \
  test_2_mem: \
    .long 0; \
  3: \
  )

  /* Test mov.l indexed store with offset 4 */
  TEST_CASE( 3, r4, 0xabcdef00, \
    mov.l test_3_val, r2; \
    mova test_3_mem, r0; \
    mov r0, r3; \
    mov #4, r0; \
    mov.l r2, @(r0, r3); \
    add #4, r3; \
    mov.l @r3, r4; \
    bra 3f; \
    nop; \
    .align 2; \
  test_3_val: \
    .long 0xabcdef00; \
  test_3_mem: \
    .long 0, 0; \
  3: \
  )

  /* Test mov.l indexed store array */
  TEST_CASE( 4, r5, 0x77777777, \
    mov.l test_4_val, r2; \
    mova test_4_mem, r0; \
    mov r0, r3; \
    mov #8, r0; \
    mov.l r2, @(r0, r3); \
    add #8, r3; \
    mov.l @r3, r5; \
    bra 3f; \
    nop; \
    .align 2; \
  test_4_val: \
    .long 0x77777777; \
  test_4_mem: \
    .long 0, 0, 0; \
  3: \
  )

  /* Test mov.l indexed store multiple */
  TEST_CASE( 5, r6, 0x99999999, \
    mov.l test_5_val1, r1; \
    mov.l test_5_val2, r2; \
    mova test_5_mem, r0; \
    mov r0, r3; \
    mov #0, r0; \
    mov.l r1, @(r0, r3); \
    mov #4, r0; \
    mov.l r2, @(r0, r3); \
    add #4, r3; \
    mov.l @r3, r6; \
    bra 3f; \
    nop; \
    .align 2; \
  test_5_val1: \
    .long 0x88888888; \
  test_5_val2: \
    .long 0x99999999; \
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
