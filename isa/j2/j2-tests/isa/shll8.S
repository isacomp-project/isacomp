/* j2 (SuperH-2) SHLL8 instruction tests */
/* SHLL8 shifts left logical by 8 bits */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Shift left logical 8 tests
   *-------------------------------------------------------------*/

  /* Test shll8 basic */
  TEST_CASE( 2, r1, 0x00000100, \
    mov #1, r1; \
    shll8 r1; \
  )

  /* Test shll8 zero */
  TEST_CASE( 3, r1, 0x00000000, \
    mov #0, r1; \
    shll8 r1; \
  )

  /* Test shll8 with byte value */
  TEST_CASE( 4, r1, 0x00005500, \
    mov #0x55, r1; \
    shll8 r1; \
  )

  /* Test shll8 bit shift: mov #0xff sign-extends to 0xffffffff */
  TEST_CASE( 5, r1, 0xffffff00, \
    mov #0xff, r1; \
    shll8 r1; \
  )

  /* Test shll8 overflow */
  TEST_CASE( 6, r1, 0x00000000, \
    mov.l test_6_val, r1; \
    shll8 r1; \
    bra 3f; \
    nop; \
    .align 2; \
  test_6_val: \
    .long 0x01000000; \
  3: \
  )

  /* Test shll8 multiple times */
  TEST_CASE( 7, r1, 0x01000000, \
    mov #1, r1; \
    shll8 r1; \
    shll8 r1; \
    shll8 r1; \
  )

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
