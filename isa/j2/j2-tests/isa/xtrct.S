/* j2 (SuperH-2) XTRCT instruction tests */
/* XTRCT extracts middle 32 bits from Rm:Rn into Rn */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Extract middle tests
   *-------------------------------------------------------------*/

  /* Test xtrct basic */
  TEST_CASE( 2, r2, 0x56781234, \
    mov.l test_2_val1, r1; \
    mov.l test_2_val2, r2; \
    xtrct r1, r2; \
    bra 3f; \
    nop; \
    .align 2; \
  test_2_val1: \
    .long 0x12345678; \
  test_2_val2: \
    .long 0x9abcdef0; \
  3: \
  )

  /* Test xtrct with zeros */
  TEST_CASE( 3, r2, 0x00000000, \
    mov #0, r1; \
    mov #0, r2; \
    xtrct r1, r2; \
  )

  /* Test xtrct pattern */
  TEST_CASE( 4, r2, 0xffff0000, \
    mov.l test_4_val1, r1; \
    mov.l test_4_val2, r2; \
    xtrct r1, r2; \
    bra 3f; \
    nop; \
    .align 2; \
  test_4_val1: \
    .long 0x0000ffff; \
  test_4_val2: \
    .long 0xffff0000; \
  3: \
  )

  /* Test xtrct extracts upper 16 of Rn, lower 16 of Rm */
  TEST_CASE( 5, r2, 0xabcd1234, \
    mov.l test_5_val1, r1; \
    mov.l test_5_val2, r2; \
    xtrct r1, r2; \
    bra 3f; \
    nop; \
    .align 2; \
  test_5_val1: \
    .long 0xabcd0000; \
  test_5_val2: \
    .long 0x00001234; \
  3: \
  )

  /* Test xtrct with 0xffffffff */
  TEST_CASE( 6, r2, 0xffffffff, \
    mov #-1, r1; \
    mov #-1, r2; \
    xtrct r1, r2; \
  )

  /* Test xtrct alignment extraction */
  TEST_CASE( 7, r2, 0x3456789a, \
    mov.l test_7_val1, r1; \
    mov.l test_7_val2, r2; \
    xtrct r1, r2; \
    bra 3f; \
    nop; \
    .align 2; \
  test_7_val1: \
    .long 0x12345678; \
  test_7_val2: \
    .long 0x9abcdef0; \
  3: \
  )

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
