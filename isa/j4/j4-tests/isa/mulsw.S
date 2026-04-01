/* j2 (SuperH-2) MULS.W instruction tests */
/* MULS.W Rm, Rn multiplies signed 16-bit values, stores result in MACL */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Multiply signed word tests
   *-------------------------------------------------------------*/

  /* Test basic muls.w */
  TEST_CASE( 2, r3, 0x0000000c, \
    mov #3, r1; \
    mov #4, r2; \
    muls.w r2, r1; \
    sts macl, r3; \
  )

  /* Test muls.w with zero */
  TEST_CASE( 3, r3, 0x00000000, \
    mov #5, r1; \
    mov #0, r2; \
    muls.w r2, r1; \
    sts macl, r3; \
  )

  /* Test muls.w positive * positive */
  TEST_CASE( 4, r3, 0x00000190, \
    mov #25, r1; \
    mov #16, r2; \
    muls.w r2, r1; \
    sts macl, r3; \
  )

  /* Test muls.w positive * negative */
  TEST_CASE( 5, r3, 0xffffffd8, \
    mov #5, r1; \
    mov #-8, r2; \
    muls.w r2, r1; \
    sts macl, r3; \
  )

  /* Test muls.w negative * negative */
  TEST_CASE( 6, r3, 0x00000032, \
    mov #-10, r1; \
    mov #-5, r2; \
    muls.w r2, r1; \
    sts macl, r3; \
  )

  /* Test muls.w with -1 */
  TEST_CASE( 7, r3, 0xfffffffa, \
    mov #6, r1; \
    mov #-1, r2; \
    muls.w r2, r1; \
    sts macl, r3; \
  )

  /* Test muls.w large values */
  TEST_CASE( 8, r3, 0x3fff0001, \
    mov.l test_8_val1, r1; \
    mov.l test_8_val2, r2; \
    muls.w r2, r1; \
    sts macl, r3; \
    bra 3f; \
    nop; \
    .align 2; \
  test_8_val1: \
    .long 0x00007fff; \
  test_8_val2: \
    .long 0x00007fff; \
  3: \
  )

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
