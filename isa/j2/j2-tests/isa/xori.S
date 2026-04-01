/* j2 (SuperH-2) XORI instruction tests */
/* XOR immediate with R0: xor #imm, r0 */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Logical tests - XOR immediate
   *-------------------------------------------------------------*/

  /* xor #0x00, r0 with r0=0x55 = 0x55 */
  TEST_CASE( 2, r1, 0x00000055, \
    mov #0x55, r0; \
    xor #0x00, r0; \
    mov r0, r1; \
  )

  /* xor #0xff, r0 with r0=0x00 = 0xff */
  TEST_CASE( 3, r1, 0x000000ff, \
    mov #0x00, r0; \
    xor #0xff, r0; \
    mov r0, r1; \
  )

  /* xor #0xff, r0 with r0=-1 = 0 (lower byte) */
  TEST_CASE( 4, r1, 0xffffff00, \
    mov #-1, r0; \
    xor #0xff, r0; \
    mov r0, r1; \
  )

  /* xor #0xaa, r0 with r0=0x55 = 0xff */
  TEST_CASE( 5, r1, 0x000000ff, \
    mov #0x55, r0; \
    xor #0xaa, r0; \
    mov r0, r1; \
  )

  /* xor #0x0f, r0 with r0=0x5a = 0x55 */
  TEST_CASE( 6, r1, 0x00000055, \
    mov #0x5a, r0; \
    xor #0x0f, r0; \
    mov r0, r1; \
  )

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
