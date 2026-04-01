/* j2 (SuperH-2) ORI instruction tests */
/* OR immediate with R0: or #imm, r0 */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Logical tests - OR immediate
   *-------------------------------------------------------------*/

  /* or #0x55, r0 with r0=0x00 = 0x55 */
  TEST_CASE( 2, r1, 0x00000055, \
    mov #0, r0; \
    or #0x55, r0; \
    mov r0, r1; \
  )

  /* or #0xf0, r0 with r0=0x0f = 0xff */
  TEST_CASE( 3, r1, 0x000000ff, \
    mov #0x0f, r0; \
    or #0xf0, r0; \
    mov r0, r1; \
  )

  /* or #0, r0 with r0=0x55 = 0x55 */
  TEST_CASE( 4, r1, 0x00000055, \
    mov #0x55, r0; \
    or #0, r0; \
    mov r0, r1; \
  )

  /* or #0xaa, r0 with r0=0x55 = 0xff */
  TEST_CASE( 5, r1, 0x000000ff, \
    mov #0x55, r0; \
    or #0xaa, r0; \
    mov r0, r1; \
  )

  /* or #0x80, r0 with r0=0x7f = 0xff */
  TEST_CASE( 6, r1, 0x000000ff, \
    mov #0x7f, r0; \
    or #0x80, r0; \
    mov r0, r1; \
  )

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
