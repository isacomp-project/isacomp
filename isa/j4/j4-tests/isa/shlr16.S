/* j2 (SuperH-2) SHLR16 instruction tests */
/* SHLR16 shifts right logical by 16 bits */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Shift right logical 16 tests
   *-------------------------------------------------------------*/

  /* Test shlr16 basic */
  TEST_CASE( 2, r1, 0x00000001, \
    mov.l test_2_val, r1; \
    shlr16 r1; \
    bra 3f; \
    nop; \
    .align 2; \
  test_2_val: \
    .long 0x00010000; \
  3: \
  )

  /* Test shlr16 zero */
  TEST_CASE( 3, r1, 0x00000000, \
    mov #0, r1; \
    shlr16 r1; \
  )

  /* Test shlr16 with word value */
  TEST_CASE( 4, r1, 0x00001234, \
    mov.l test_4_val, r1; \
    shlr16 r1; \
    bra 3f; \
    nop; \
    .align 2; \
  test_4_val: \
    .long 0x12340000; \
  3: \
  )

  /* Test shlr16 no sign extension */
  TEST_CASE( 5, r1, 0x0000ffff, \
    mov.l test_5_val, r1; \
    shlr16 r1; \
    bra 3f; \
    nop; \
    .align 2; \
  test_5_val: \
    .long 0xffff0000; \
  3: \
  )

  /* Test shlr16 with 0xffffffff */
  TEST_CASE( 6, r1, 0x0000ffff, \
    mov.l test_6_val, r1; \
    shlr16 r1; \
    bra 3f; \
    nop; \
    .align 2; \
  test_6_val: \
    .long 0xffffffff; \
  3: \
  )

  /* Test shlr16 twice = 32-bit shift (zero) */
  TEST_CASE( 7, r1, 0x00000000, \
    mov.l test_7_val, r1; \
    shlr16 r1; \
    shlr16 r1; \
    bra 3f; \
    nop; \
    .align 2; \
  test_7_val: \
    .long 0x80000000; \
  3: \
  )

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
