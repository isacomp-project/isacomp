/* j2 (SuperH-2) SHLL instruction tests */
/* SHLL shifts left by 1 bit, MSB goes to T */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Shift left logical tests
   *-------------------------------------------------------------*/

  /* shll 0 = 0 */
  TEST_CASE( 2, r1, 0x00000000, \
    mov #0, r1; \
    shll r1; \
  )

  /* shll 1 = 2 */
  TEST_CASE( 3, r1, 0x00000002, \
    mov #1, r1; \
    shll r1; \
  )

  /* shll 0x40 = 0x80 */
  TEST_CASE( 4, r1, 0x00000080, \
    mov #0x40, r1; \
    shll r1; \
  )

  /* shll -1 = -2 (0xfffffffe) */
  TEST_CASE( 5, r1, 0xfffffffe, \
    mov #-1, r1; \
    shll r1; \
  )

  /* Multiple shifts: 1 << 3 = 8 */
  TEST_CASE( 6, r1, 0x00000008, \
    mov #1, r1; \
    shll r1; \
    shll r1; \
    shll r1; \
  )

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
