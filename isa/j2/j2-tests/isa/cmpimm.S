/* j2 (SuperH-2) CMP/EQ (immediate) instruction tests */
/* CMP/EQ #imm, R0 sets T if R0 == sign-extended immediate */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Comparison tests - Compare immediate with R0
   *-------------------------------------------------------------*/

  /* Test cmp/eq #5, r0 when r0=5 (true) */
  TEST_CASE( 2, r1, 0x00000001, \
    mov #5, r0; \
    cmp/eq #5, r0; \
    movt r1; \
  )

  /* Test cmp/eq #5, r0 when r0=3 (false) */
  TEST_CASE( 3, r1, 0x00000000, \
    mov #3, r0; \
    cmp/eq #5, r0; \
    movt r1; \
  )

  /* Test cmp/eq #0, r0 when r0=0 (true) */
  TEST_CASE( 4, r1, 0x00000001, \
    mov #0, r0; \
    cmp/eq #0, r0; \
    movt r1; \
  )

  /* Test cmp/eq #-1, r0 when r0=-1 (true) */
  TEST_CASE( 5, r1, 0x00000001, \
    mov #-1, r0; \
    cmp/eq #-1, r0; \
    movt r1; \
  )

  /* Test cmp/eq #-1, r0 when r0=1 (false) */
  TEST_CASE( 6, r1, 0x00000000, \
    mov #1, r0; \
    cmp/eq #-1, r0; \
    movt r1; \
  )

  /* Test cmp/eq #127, r0 when r0=127 (true) */
  TEST_CASE( 7, r1, 0x00000001, \
    mov #127, r0; \
    cmp/eq #127, r0; \
    movt r1; \
  )

  /* Test cmp/eq #-128, r0 when r0=-128 (true) */
  TEST_CASE( 8, r1, 0x00000001, \
    mov #-128, r0; \
    cmp/eq #-128, r0; \
    movt r1; \
  )

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
