/* j2 (SuperH-2) MUL.L instruction tests */
/* MUL.L Rm, Rn multiplies 32-bit values, stores lower 32 bits in MACL */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Multiply long tests
   *-------------------------------------------------------------*/

  /* Test basic mul.l */
  TEST_CASE( 2, r3, 0x0000000c, \
    mov #3, r1; \
    mov #4, r2; \
    mul.l r2, r1; \
    sts macl, r3; \
  )

  /* Test mul.l with zero */
  TEST_CASE( 3, r3, 0x00000000, \
    mov #5, r1; \
    mov #0, r2; \
    mul.l r2, r1; \
    sts macl, r3; \
  )

  /* Test mul.l with one */
  TEST_CASE( 4, r3, 0x0000007b, \
    mov #123, r1; \
    mov #1, r2; \
    mul.l r2, r1; \
    sts macl, r3; \
  )

  /* Test mul.l with negative numbers */
  TEST_CASE( 5, r3, 0x0000000a, \
    mov #-5, r1; \
    mov #-2, r2; \
    mul.l r2, r1; \
    sts macl, r3; \
  )

  /* Test mul.l overflow (lower 32 bits) */
  TEST_CASE( 6, r3, 0x00000000, \
    mov.l test_6_val, r1; \
    mov #2, r2; \
    mul.l r2, r1; \
    sts macl, r3; \
    bra 3f; \
    nop; \
    .align 2; \
  test_6_val: \
    .long 0x80000000; \
  3: \
  )

  /* Test mul.l large values */
  TEST_CASE( 7, r3, 0xfffffffa, \
    mov #-1, r1; \
    mov #6, r2; \
    mul.l r2, r1; \
    sts macl, r3; \
  )

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
