/* j2 (SuperH-2) CMP/HS instruction tests */
/* CMP/HS sets T if Rn >= Rm (unsigned) */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Comparison tests - Higher or same (unsigned)
   *-------------------------------------------------------------*/

  /* Test 5 >= 3 (true) */
  TEST_CASE( 2, r3, 0x00000001, \
    mov #5, r1; \
    mov #3, r2; \
    cmp/hs r2, r1; \
    movt r3; \
  )

  /* Test 3 >= 5 (false) */
  TEST_CASE( 3, r3, 0x00000000, \
    mov #3, r1; \
    mov #5, r2; \
    cmp/hs r2, r1; \
    movt r3; \
  )

  /* Test 5 >= 5 (true) */
  TEST_CASE( 4, r3, 0x00000001, \
    mov #5, r1; \
    mov #5, r2; \
    cmp/hs r2, r1; \
    movt r3; \
  )

  /* Test 0 >= 0 (true) */
  TEST_CASE( 5, r3, 0x00000001, \
    mov #0, r1; \
    mov #0, r2; \
    cmp/hs r2, r1; \
    movt r3; \
  )

  /* Test 0xffffffff >= 0x7fffffff (true, unsigned) */
  TEST_CASE( 6, r3, 0x00000001, \
    mov.l test_6_val1, r1; \
    mov.l test_6_val2, r2; \
    cmp/hs r2, r1; \
    movt r3; \
    bra 3f; \
    nop; \
    .align 2; \
  test_6_val1: \
    .long 0xffffffff; \
  test_6_val2: \
    .long 0x7fffffff; \
  3: \
  )

  /* Test 0x7fffffff >= 0xffffffff (false, unsigned) */
  TEST_CASE( 7, r3, 0x00000000, \
    mov.l test_7_val1, r1; \
    mov.l test_7_val2, r2; \
    cmp/hs r2, r1; \
    movt r3; \
    bra 3f; \
    nop; \
    .align 2; \
  test_7_val1: \
    .long 0x7fffffff; \
  test_7_val2: \
    .long 0xffffffff; \
  3: \
  )

  /* Test 0xffffffff >= 0xffffffff (true) */
  TEST_CASE( 8, r3, 0x00000001, \
    mov.l test_8_val1, r1; \
    mov.l test_8_val2, r2; \
    cmp/hs r2, r1; \
    movt r3; \
    bra 3f; \
    nop; \
    .align 2; \
  test_8_val1: \
    .long 0xffffffff; \
  test_8_val2: \
    .long 0xffffffff; \
  3: \
  )

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
