/* j2 (SuperH-2) TST immediate instruction tests */
/* TST #imm, R0 performs AND with R0 and sets T if result is zero */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Test immediate tests
   *-------------------------------------------------------------*/

  /* Test tst #imm with no common bits (sets T) */
  TEST_CASE( 2, r1, 0x00000001, \
    mov #0x0f, r0; \
    tst #0xf0, r0; \
    movt r1; \
  )

  /* Test tst #imm with common bits (clears T) */
  TEST_CASE( 3, r1, 0x00000000, \
    mov #0x0f, r0; \
    tst #0x03, r0; \
    movt r1; \
  )

  /* Test tst #imm with zero r0 (sets T) */
  TEST_CASE( 4, r1, 0x00000001, \
    mov #0, r0; \
    tst #0xff, r0; \
    movt r1; \
  )

  /* Test tst #imm with zero immediate (sets T) */
  TEST_CASE( 5, r1, 0x00000001, \
    mov #0xff, r0; \
    tst #0x00, r0; \
    movt r1; \
  )

  /* Test tst #imm bit mask */
  TEST_CASE( 6, r1, 0x00000000, \
    mov #0x55, r0; \
    tst #0x01, r0; \
    movt r1; \
  )

  /* Test tst #imm with 0xaa and 0x55 (sets T) */
  TEST_CASE( 7, r1, 0x00000001, \
    mov #0x55, r0; \
    tst #0xaa, r0; \
    movt r1; \
  )

  /* Test tst #imm with all bits */
  TEST_CASE( 8, r1, 0x00000000, \
    mov #0xff, r0; \
    tst #0xff, r0; \
    movt r1; \
  )

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
