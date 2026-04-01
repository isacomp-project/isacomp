/* j2 (SuperH-2) SWAP.B instruction tests */
/* SWAP.B swaps lower 2 bytes within lower word */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Swap bytes tests
   *-------------------------------------------------------------*/

  /* Test swap.b basic */
  TEST_CASE( 2, r2, 0x00003412, \
    mov.l test_2_val, r1; \
    swap.b r1, r2; \
    bra 3f; \
    nop; \
    .align 2; \
  test_2_val: \
    .long 0x00001234; \
  3: \
  )

  /* Test swap.b with zero */
  TEST_CASE( 3, r2, 0x00000000, \
    mov #0, r1; \
    swap.b r1, r2; \
  )

  /* Test swap.b upper word unchanged */
  TEST_CASE( 4, r2, 0xabcd7856, \
    mov.l test_4_val, r1; \
    swap.b r1, r2; \
    bra 3f; \
    nop; \
    .align 2; \
  test_4_val: \
    .long 0xabcd5678; \
  3: \
  )

  /* Test swap.b with 0xff */
  TEST_CASE( 5, r2, 0x0000ff00, \
    mov #0xff, r1; \
    swap.b r1, r2; \
  )

  /* Test swap.b pattern */
  TEST_CASE( 6, r2, 0x0000aa55, \
    mov.l test_6_val, r1; \
    swap.b r1, r2; \
    bra 3f; \
    nop; \
    .align 2; \
  test_6_val: \
    .long 0x000055aa; \
  3: \
  )

  /* Test swap.b self-destination */
  TEST_CASE( 7, r1, 0x00004321, \
    mov.l test_7_val, r1; \
    swap.b r1, r1; \
    bra 3f; \
    nop; \
    .align 2; \
  test_7_val: \
    .long 0x00002143; \
  3: \
  )

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
