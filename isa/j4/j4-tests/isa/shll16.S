/* j2 (SuperH-2) SHLL16 instruction tests */
/* SHLL16 shifts left logical by 16 bits */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Shift left logical 16 tests
   *-------------------------------------------------------------*/

  /* Test shll16 basic */
  TEST_CASE( 2, r1, 0x00010000, \
    mov #1, r1; \
    shll16 r1; \
  )

  /* Test shll16 zero */
  TEST_CASE( 3, r1, 0x00000000, \
    mov #0, r1; \
    shll16 r1; \
  )

  /* Test shll16 with word value */
  TEST_CASE( 4, r1, 0x12340000, \
    mov.l test_4_val, r1; \
    shll16 r1; \
    bra 3f; \
    nop; \
    .align 2; \
  test_4_val: \
    .long 0x00001234; \
  3: \
  )

  /* Test shll16 with 0xffff */
  TEST_CASE( 5, r1, 0xffff0000, \
    mov.l test_5_val, r1; \
    shll16 r1; \
    bra 3f; \
    nop; \
    .align 2; \
  test_5_val: \
    .long 0x0000ffff; \
  3: \
  )

  /* Test shll16 overflow */
  TEST_CASE( 6, r1, 0x00000000, \
    mov.l test_6_val, r1; \
    shll16 r1; \
    bra 3f; \
    nop; \
    .align 2; \
  test_6_val: \
    .long 0x00010000; \
  3: \
  )

  /* Test shll16 twice = 32-bit shift (zero) */
  TEST_CASE( 7, r1, 0x00000000, \
    mov #1, r1; \
    shll16 r1; \
    shll16 r1; \
  )

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
