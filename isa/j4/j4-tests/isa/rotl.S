/* j2 (SuperH-2) ROTL instruction tests */
/* ROTL rotates left by 1 bit, LSB gets MSB */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Rotate left tests
   *-------------------------------------------------------------*/

  /* Test rotl basic */
  TEST_CASE( 2, r1, 0x00000002, \
    mov #1, r1; \
    rotl r1; \
  )

  /* Test rotl with bit rotation */
  TEST_CASE( 3, r1, 0x00000001, \
    mov.l test_3_val, r1; \
    rotl r1; \
    bra 3f; \
    nop; \
    .align 2; \
  test_3_val: \
    .long 0x80000000; \
  3: \
  )

  /* Test rotl MSB -> LSB */
  TEST_CASE( 4, r1, 0xffffffff, \
    mov.l test_4_val, r1; \
    rotl r1; \
    bra 3f; \
    nop; \
    .align 2; \
  test_4_val: \
    .long 0xffffffff; \
  3: \
  )

  /* Test rotl zero */
  TEST_CASE( 5, r1, 0x00000000, \
    mov #0, r1; \
    rotl r1; \
  )

  /* Test rotl multiple times */
  TEST_CASE( 6, r1, 0x00000008, \
    mov #1, r1; \
    rotl r1; \
    rotl r1; \
    rotl r1; \
  )

  /* Test rotl pattern */
  TEST_CASE( 7, r1, 0xaaaaaaaa, \
    mov.l test_7_val, r1; \
    rotl r1; \
    bra 3f; \
    nop; \
    .align 2; \
  test_7_val: \
    .long 0x55555555; \
  3: \
  )

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
