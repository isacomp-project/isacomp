/* j2 (SuperH-2) EXTU.B instruction tests */
/* EXTU.B zero-extends byte to long */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Extension tests - Zero extend byte
   *-------------------------------------------------------------*/

  /* Test extu.b with 0x7f */
  TEST_CASE( 2, r2, 0x0000007f, \
    mov #0x7f, r1; \
    extu.b r1, r2; \
  )

  /* Test extu.b with 0x80 -> 0x00000080 (zero extended) */
  TEST_CASE( 3, r2, 0x00000080, \
    mov #0x80, r1; \
    extu.b r1, r2; \
  )

  /* Test extu.b with 0xff -> 0x000000ff */
  TEST_CASE( 4, r2, 0x000000ff, \
    mov #0xff, r1; \
    extu.b r1, r2; \
  )

  /* Test extu.b with 0x00 */
  TEST_CASE( 5, r2, 0x00000000, \
    mov #0x00, r1; \
    extu.b r1, r2; \
  )

  /* Test extu.b with 0x01 */
  TEST_CASE( 6, r2, 0x00000001, \
    mov #0x01, r1; \
    extu.b r1, r2; \
  )

  /* Test extu.b ignores upper bits */
  TEST_CASE( 7, r2, 0x00000081, \
    mov.l test_7_val, r1; \
    extu.b r1, r2; \
    bra 3f; \
    nop; \
    .align 2; \
  test_7_val: \
    .long 0xffffff81; \
  3: \
  )

  /* Test extu.b self-destination */
  TEST_CASE( 8, r1, 0x000000fe, \
    mov #0xfe, r1; \
    extu.b r1, r1; \
  )

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
