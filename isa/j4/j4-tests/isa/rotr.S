/* j2 (SuperH-2) ROTR instruction tests */
/* ROTR rotates right by 1 bit, MSB gets LSB */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Rotate right tests
   *-------------------------------------------------------------*/

  /* Test rotr basic: LSB rotates to MSB */
  TEST_CASE( 2, r1, 0x80000000, \
    mov #1, r1; \
    rotr r1; \
  )

  /* Test rotr with bit rotation */
  TEST_CASE( 3, r1, 0x80000000, \
    mov #1, r1; \
    rotr r1; \
  )

  /* Test rotr LSB -> MSB */
  TEST_CASE( 4, r1, 0xffffffff, \
    mov #-1, r1; \
    rotr r1; \
  )

  /* Test rotr zero */
  TEST_CASE( 5, r1, 0x00000000, \
    mov #0, r1; \
    rotr r1; \
  )

  /* Test rotr multiple times */
  TEST_CASE( 6, r1, 0x10000000, \
    mov.l test_6_val, r1; \
    rotr r1; \
    rotr r1; \
    rotr r1; \
    bra 3f; \
    nop; \
    .align 2; \
  test_6_val: \
    .long 0x80000000; \
  3: \
  )

  /* Test rotr pattern */
  TEST_CASE( 7, r1, 0xaaaaaaaa, \
    mov.l test_7_val, r1; \
    rotr r1; \
    bra 3f; \
    nop; \
    .align 2; \
  test_7_val: \
    .long 0x55555555; \
  3: \
  )

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
