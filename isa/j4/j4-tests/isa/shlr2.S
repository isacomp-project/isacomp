/* j2 (SuperH-2) SHLR2 instruction tests */
/* SHLR2 shifts right logical by 2 bits */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Shift right logical 2 tests
   *-------------------------------------------------------------*/

  /* Test shlr2 basic */
  TEST_CASE( 2, r1, 0x00000001, \
    mov #4, r1; \
    shlr2 r1; \
  )

  /* Test shlr2 zero */
  TEST_CASE( 3, r1, 0x00000000, \
    mov #0, r1; \
    shlr2 r1; \
  )

  /* Test shlr2 with larger value */
  TEST_CASE( 4, r1, 0x00000005, \
    mov #20, r1; \
    shlr2 r1; \
  )

  /* Test shlr2 bit shift */
  TEST_CASE( 5, r1, 0x00000040, \
    mov.l test_5_val, r1; \
    shlr2 r1; \
    bra 3f; \
    nop; \
    .align 2; \
  test_5_val: \
    .long 0x00000100; \
  3: \
  )

  /* Test shlr2 no sign extension */
  TEST_CASE( 6, r1, 0x3fffffff, \
    mov.l test_6_val, r1; \
    shlr2 r1; \
    bra 3f; \
    nop; \
    .align 2; \
  test_6_val: \
    .long 0xffffffff; \
  3: \
  )

  /* Test shlr2 multiple times: 0x10000 >> 8 = 0x100 */
  TEST_CASE( 7, r1, 0x00000100, \
    mov.l test_7_val, r1; \
    shlr2 r1; \
    shlr2 r1; \
    shlr2 r1; \
    shlr2 r1; \
    bra 3f; \
    nop; \
    .align 2; \
  test_7_val: \
    .long 0x00010000; \
  3: \
  )

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
