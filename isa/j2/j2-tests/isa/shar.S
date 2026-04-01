/* j2 (SuperH-2) SHAR instruction tests */
/* SHAR shifts arithmetic right by 1 bit, preserves sign, LSB goes to T */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Shift arithmetic right tests
   *-------------------------------------------------------------*/

  /* Test shar basic */
  TEST_CASE( 2, r1, 0x00000001, \
    mov #2, r1; \
    shar r1; \
  )

  /* Test shar zero */
  TEST_CASE( 3, r1, 0x00000000, \
    mov #0, r1; \
    shar r1; \
  )

  /* Test shar LSB sets T */
  TEST_CASE( 4, r2, 0x00000001, \
    mov #3, r1; \
    shar r1; \
    movt r2; \
  )

  /* Test shar preserves sign (negative) */
  TEST_CASE( 5, r1, 0xffffffff, \
    mov #-1, r1; \
    shar r1; \
  )

  /* Test shar negative value */
  TEST_CASE( 6, r1, 0xfffffffc, \
    mov #-8, r1; \
    shar r1; \
  )

  /* Test shar sign extension */
  TEST_CASE( 7, r1, 0xc0000000, \
    mov.l test_7_val, r1; \
    shar r1; \
    bra 3f; \
    nop; \
    .align 2; \
  test_7_val: \
    .long 0x80000000; \
  3: \
  )

  /* Test shar multiple times */
  TEST_CASE( 8, r1, 0x00000001, \
    mov #8, r1; \
    shar r1; \
    shar r1; \
    shar r1; \
  )

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
