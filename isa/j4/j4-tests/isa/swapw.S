/* j2 (SuperH-2) SWAP.W instruction tests */
/* SWAP.W swaps upper and lower words */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Swap words tests
   *-------------------------------------------------------------*/

  /* Test swap.w basic */
  TEST_CASE( 2, r2, 0x56781234, \
    mov.l test_2_val, r1; \
    swap.w r1, r2; \
    bra 3f; \
    nop; \
    .align 2; \
  test_2_val: \
    .long 0x12345678; \
  3: \
  )

  /* Test swap.w with zero */
  TEST_CASE( 3, r2, 0x00000000, \
    mov #0, r1; \
    swap.w r1, r2; \
  )

  /* Test swap.w pattern */
  TEST_CASE( 4, r2, 0xabcdffff, \
    mov.l test_4_val, r1; \
    swap.w r1, r2; \
    bra 3f; \
    nop; \
    .align 2; \
  test_4_val: \
    .long 0xffffabcd; \
  3: \
  )

  /* Test swap.w symmetric */
  TEST_CASE( 5, r2, 0x12341234, \
    mov.l test_5_val, r1; \
    swap.w r1, r2; \
    bra 3f; \
    nop; \
    .align 2; \
  test_5_val: \
    .long 0x12341234; \
  3: \
  )

  /* Test swap.w twice returns original */
  TEST_CASE( 6, r2, 0xabcd1234, \
    mov.l test_6_val, r1; \
    swap.w r1, r2; \
    swap.w r2, r2; \
    bra 3f; \
    nop; \
    .align 2; \
  test_6_val: \
    .long 0xabcd1234; \
  3: \
  )

  /* Test swap.w self-destination */
  TEST_CASE( 7, r1, 0x5678abcd, \
    mov.l test_7_val, r1; \
    swap.w r1, r1; \
    bra 3f; \
    nop; \
    .align 2; \
  test_7_val: \
    .long 0xabcd5678; \
  3: \
  )

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
