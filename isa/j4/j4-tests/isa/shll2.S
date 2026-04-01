/* j2 (SuperH-2) SHLL2 instruction tests */
/* SHLL2 shifts left logical by 2 bits */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Shift left logical 2 tests
   *-------------------------------------------------------------*/

  /* Test shll2 basic */
  TEST_CASE( 2, r1, 0x00000004, \
    mov #1, r1; \
    shll2 r1; \
  )

  /* Test shll2 zero */
  TEST_CASE( 3, r1, 0x00000000, \
    mov #0, r1; \
    shll2 r1; \
  )

  /* Test shll2 with larger value */
  TEST_CASE( 4, r1, 0x00000014, \
    mov #5, r1; \
    shll2 r1; \
  )

  /* Test shll2 bit shift */
  TEST_CASE( 5, r1, 0x00000100, \
    mov #0x40, r1; \
    shll2 r1; \
  )

  /* Test shll2 overflow */
  TEST_CASE( 6, r1, 0x00000000, \
    mov.l test_6_val, r1; \
    shll2 r1; \
    bra 3f; \
    nop; \
    .align 2; \
  test_6_val: \
    .long 0x40000000; \
  3: \
  )

  /* Test shll2 multiple times: 1 << 8 = 0x100 */
  TEST_CASE( 7, r1, 0x00000100, \
    mov #1, r1; \
    shll2 r1; \
    shll2 r1; \
    shll2 r1; \
    shll2 r1; \
  )

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
