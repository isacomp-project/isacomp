/* j2 (SuperH-2) CMP/PL instruction tests */
/* CMP/PL sets T if Rn > 0 (signed) */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Comparison tests - Positive (> 0)
   *-------------------------------------------------------------*/

  /* Test cmp/pl with 1 (true) */
  TEST_CASE( 2, r2, 0x00000001, \
    mov #1, r1; \
    cmp/pl r1; \
    movt r2; \
  )

  /* Test cmp/pl with 0 (false) */
  TEST_CASE( 3, r2, 0x00000000, \
    mov #0, r1; \
    cmp/pl r1; \
    movt r2; \
  )

  /* Test cmp/pl with -1 (false) */
  TEST_CASE( 4, r2, 0x00000000, \
    mov #-1, r1; \
    cmp/pl r1; \
    movt r2; \
  )

  /* Test cmp/pl with 127 (true) */
  TEST_CASE( 5, r2, 0x00000001, \
    mov #127, r1; \
    cmp/pl r1; \
    movt r2; \
  )

  /* Test cmp/pl with -128 (false) */
  TEST_CASE( 6, r2, 0x00000000, \
    mov #-128, r1; \
    cmp/pl r1; \
    movt r2; \
  )

  /* Test cmp/pl with 0x7fffffff (true) */
  TEST_CASE( 7, r2, 0x00000001, \
    mov.l test_7_val, r1; \
    cmp/pl r1; \
    movt r2; \
    bra 3f; \
    nop; \
    .align 2; \
  test_7_val: \
    .long 0x7fffffff; \
  3: \
  )

  /* Test cmp/pl with 0x80000000 (false) */
  TEST_CASE( 8, r2, 0x00000000, \
    mov.l test_8_val, r1; \
    cmp/pl r1; \
    movt r2; \
    bra 3f; \
    nop; \
    .align 2; \
  test_8_val: \
    .long 0x80000000; \
  3: \
  )

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
