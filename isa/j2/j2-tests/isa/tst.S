/* j2 (SuperH-2) TST instruction tests */
/* TST Rm, Rn performs AND and sets T if result is zero */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Test logical tests
   *-------------------------------------------------------------*/

  /* Test tst with no common bits (sets T) */
  TEST_CASE( 2, r3, 0x00000001, \
    mov #0x0f, r1; \
    mov #0xf0, r2; \
    tst r2, r1; \
    movt r3; \
  )

  /* Test tst with common bits (clears T) */
  TEST_CASE( 3, r3, 0x00000000, \
    mov #0x0f, r1; \
    mov #0x03, r2; \
    tst r2, r1; \
    movt r3; \
  )

  /* Test tst with zero operand (sets T) */
  TEST_CASE( 4, r3, 0x00000001, \
    mov #0, r1; \
    mov #0xff, r2; \
    tst r2, r1; \
    movt r3; \
  )

  /* Test tst with same value (clears T) */
  TEST_CASE( 5, r3, 0x00000000, \
    mov #0x55, r1; \
    mov #0x55, r2; \
    tst r2, r1; \
    movt r3; \
  )

  /* Test tst with all bits set (clears T) */
  TEST_CASE( 6, r3, 0x00000000, \
    mov #-1, r1; \
    mov #1, r2; \
    tst r2, r1; \
    movt r3; \
  )

  /* Test tst bit mask: 0x12345678 & 0xabcd0000 = 0x02040000 (non-zero, T=0) */
  TEST_CASE( 7, r3, 0x00000000, \
    mov.l test_7_val1, r1; \
    mov.l test_7_val2, r2; \
    tst r2, r1; \
    movt r3; \
    bra 3f; \
    nop; \
    .align 2; \
  test_7_val1: \
    .long 0x12345678; \
  test_7_val2: \
    .long 0xabcd0000; \
  3: \
  )

  /* Test tst both zero (sets T) */
  TEST_CASE( 8, r3, 0x00000001, \
    mov #0, r1; \
    mov #0, r2; \
    tst r2, r1; \
    movt r3; \
  )

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
