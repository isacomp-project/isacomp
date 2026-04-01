/* j2 (SuperH-2) EXTS.B instruction tests */
/* EXTS.B sign-extends byte to long */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Extension tests - Sign extend byte
   *-------------------------------------------------------------*/

  /* Test exts.b with positive value 0x7f */
  TEST_CASE( 2, r2, 0x0000007f, \
    mov #0x7f, r1; \
    exts.b r1, r2; \
  )

  /* Test exts.b with negative value 0x80 -> 0xffffff80 */
  TEST_CASE( 3, r2, 0xffffff80, \
    mov #0x80, r1; \
    exts.b r1, r2; \
  )

  /* Test exts.b with 0xff -> 0xffffffff */
  TEST_CASE( 4, r2, 0xffffffff, \
    mov #0xff, r1; \
    exts.b r1, r2; \
  )

  /* Test exts.b with 0x00 */
  TEST_CASE( 5, r2, 0x00000000, \
    mov #0x00, r1; \
    exts.b r1, r2; \
  )

  /* Test exts.b with 0x01 */
  TEST_CASE( 6, r2, 0x00000001, \
    mov #0x01, r1; \
    exts.b r1, r2; \
  )

  /* Test exts.b ignores upper bits */
  TEST_CASE( 7, r2, 0xffffff81, \
    mov.l test_7_val, r1; \
    exts.b r1, r2; \
    bra 3f; \
    nop; \
    .align 2; \
  test_7_val: \
    .long 0x12345681; \
  3: \
  )

  /* Test exts.b self-destination */
  TEST_CASE( 8, r1, 0xfffffffe, \
    mov #0xfe, r1; \
    exts.b r1, r1; \
  )

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
