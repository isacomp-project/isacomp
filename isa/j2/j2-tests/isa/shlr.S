/* j2 (SuperH-2) SHLR instruction tests */
/* SHLR shifts right by 1 bit (logical), LSB goes to T */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Shift right logical tests
   *-------------------------------------------------------------*/

  /* shlr 0 = 0 */
  TEST_CASE( 2, r1, 0x00000000, \
    mov #0, r1; \
    shlr r1; \
  )

  /* shlr 2 = 1 */
  TEST_CASE( 3, r1, 0x00000001, \
    mov #2, r1; \
    shlr r1; \
  )

  /* shlr 0x80 (sign-extended to 0xffffff80) >> 1 = 0x7fffffc0 */
  TEST_CASE( 4, r1, 0x7fffffc0, \
    mov #-128, r1; \
    shlr r1; \
  )

  /* shlr 1 = 0 */
  TEST_CASE( 5, r1, 0x00000000, \
    mov #1, r1; \
    shlr r1; \
  )

  /* Multiple shifts: 64 >> 3 = 8 */
  TEST_CASE( 6, r1, 0x00000008, \
    mov #64, r1; \
    shlr r1; \
    shlr r1; \
    shlr r1; \
  )

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
