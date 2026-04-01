/* j2 (SuperH-2) MULU.W instruction tests */
/* MULU.W Rm, Rn multiplies unsigned 16-bit values, stores result in MACL */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Multiply unsigned word tests
   *-------------------------------------------------------------*/

  /* Test basic mulu.w */
  TEST_CASE( 2, r3, 0x0000000c, \
    mov #3, r1; \
    mov #4, r2; \
    mulu.w r2, r1; \
    sts macl, r3; \
  )

  /* Test mulu.w with zero */
  TEST_CASE( 3, r3, 0x00000000, \
    mov #5, r1; \
    mov #0, r2; \
    mulu.w r2, r1; \
    sts macl, r3; \
  )

  /* Test mulu.w with one */
  TEST_CASE( 4, r3, 0x0000007b, \
    mov #123, r1; \
    mov #1, r2; \
    mulu.w r2, r1; \
    sts macl, r3; \
  )

  /* Test mulu.w small values */
  TEST_CASE( 5, r3, 0x00000190, \
    mov #25, r1; \
    mov #16, r2; \
    mulu.w r2, r1; \
    sts macl, r3; \
  )

  /* Test mulu.w with 0xff: sign-extends to 0xffff, 0xffff*0xffff=0xfffe0001 */
  TEST_CASE( 6, r3, 0xfffe0001, \
    mov #0xff, r1; \
    mov #0xff, r2; \
    mulu.w r2, r1; \
    sts macl, r3; \
  )

  /* Test mulu.w large unsigned values: 0xfffe*0x3fff=0x3ffe8002 */
  TEST_CASE( 7, r3, 0x3ffe8002, \
    mov.l test_7_val1, r1; \
    mov.l test_7_val2, r2; \
    mulu.w r2, r1; \
    sts macl, r3; \
    bra 3f; \
    nop; \
    .align 2; \
  test_7_val1: \
    .long 0x0000fffe; \
  test_7_val2: \
    .long 0x00003fff; \
  3: \
  )

  /* Test mulu.w max unsigned 16-bit */
  TEST_CASE( 8, r3, 0xfffe0001, \
    mov.l test_8_val, r1; \
    mov r1, r2; \
    mulu.w r2, r1; \
    sts macl, r3; \
    bra 3f; \
    nop; \
    .align 2; \
  test_8_val: \
    .long 0x0000ffff; \
  3: \
  )

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
