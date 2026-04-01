/* j2 (SuperH-2) ANDI instruction tests */
/* AND immediate with R0: and #imm, r0 */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Logical tests - AND immediate
   *-------------------------------------------------------------*/

  /* and #0x55, r0 with r0=0xff = 0x55 */
  TEST_CASE( 2, r1, 0x00000055, \
    mov #-1, r0; \
    and #0x55, r0; \
    mov r0, r1; \
  )

  /* and #0x0f, r0 with r0=0x55 = 0x05 */
  TEST_CASE( 3, r1, 0x00000005, \
    mov #0x55, r0; \
    and #0x0f, r0; \
    mov r0, r1; \
  )

  /* and #0, r0 with r0=0x7f = 0x00 */
  TEST_CASE( 4, r1, 0x00000000, \
    mov #0x7f, r0; \
    and #0, r0; \
    mov r0, r1; \
  )

  /* and #0xaa, r0 with r0=0x55 = 0x00 */
  TEST_CASE( 5, r1, 0x00000000, \
    mov #0x55, r0; \
    and #0xaa, r0; \
    mov r0, r1; \
  )

  /* and #0xf0, r0 with r0=0x7f = 0x70 */
  TEST_CASE( 6, r1, 0x00000070, \
    mov #0x7f, r0; \
    and #0xf0, r0; \
    mov r0, r1; \
  )

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
