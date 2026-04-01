/* j2 (SuperH-2) ADD #imm instruction tests */
/* ADD #imm, Rn - adds sign-extended 8-bit immediate to Rn */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Add immediate tests
   *-------------------------------------------------------------*/

  /* 0 + 0 = 0 */
  TEST_CASE( 2, r1, 0x00000000, \
    mov #0, r1; \
    add #0, r1; \
  )

  /* 0 + 1 = 1 */
  TEST_CASE( 3, r1, 0x00000001, \
    mov #0, r1; \
    add #1, r1; \
  )

  /* 5 + 7 = 12 */
  TEST_CASE( 4, r1, 0x0000000c, \
    mov #5, r1; \
    add #7, r1; \
  )

  /* 10 + (-3) = 7 */
  TEST_CASE( 5, r1, 0x00000007, \
    mov #10, r1; \
    add #-3, r1; \
  )

  /* 0 + 127 = 127 */
  TEST_CASE( 6, r1, 0x0000007f, \
    mov #0, r1; \
    add #127, r1; \
  )

  /* 0 + (-128) = -128 */
  TEST_CASE( 7, r1, 0xffffff80, \
    mov #0, r1; \
    add #-128, r1; \
  )

  /* Accumulating adds: 1 + 2 + 3 = 6 */
  TEST_CASE( 8, r1, 0x00000006, \
    mov #1, r1; \
    add #2, r1; \
    add #3, r1; \
  )

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
