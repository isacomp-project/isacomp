/* j2 (SuperH-2) SHLR8 instruction tests */
/* SHLR8 shifts right logical by 8 bits */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Shift right logical 8 tests
   *-------------------------------------------------------------*/

  /* Test shlr8 basic */
  TEST_CASE( 2, r1, 0x00000001, \
    mov.l test_2_val, r1; \
    shlr8 r1; \
    bra 3f; \
    nop; \
    .align 2; \
  test_2_val: \
    .long 0x00000100; \
  3: \
  )

  /* Test shlr8 zero */
  TEST_CASE( 3, r1, 0x00000000, \
    mov #0, r1; \
    shlr8 r1; \
  )

  /* Test shlr8 with byte value */
  TEST_CASE( 4, r1, 0x00000055, \
    mov.l test_4_val, r1; \
    shlr8 r1; \
    bra 3f; \
    nop; \
    .align 2; \
  test_4_val: \
    .long 0x00005500; \
  3: \
  )

  /* Test shlr8 no sign extension */
  TEST_CASE( 5, r1, 0x00ffffff, \
    mov.l test_5_val, r1; \
    shlr8 r1; \
    bra 3f; \
    nop; \
    .align 2; \
  test_5_val: \
    .long 0xffffffff; \
  3: \
  )

  /* Test shlr8 bit shift */
  TEST_CASE( 6, r1, 0x000000ff, \
    mov.l test_6_val, r1; \
    shlr8 r1; \
    bra 3f; \
    nop; \
    .align 2; \
  test_6_val: \
    .long 0x0000ff00; \
  3: \
  )

  /* Test shlr8 multiple times */
  TEST_CASE( 7, r1, 0x00000001, \
    mov.l test_7_val, r1; \
    shlr8 r1; \
    shlr8 r1; \
    shlr8 r1; \
    bra 3f; \
    nop; \
    .align 2; \
  test_7_val: \
    .long 0x01000000; \
  3: \
  )

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
