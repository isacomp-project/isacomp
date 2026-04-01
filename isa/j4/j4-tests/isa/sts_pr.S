/* j2 (SuperH-2) STS from PR instruction tests */
/* STS PR, Rn stores procedure register to register */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Store from PR tests
   *-------------------------------------------------------------*/

  /* Test sts from pr after bsr */
  TEST_CASE( 2, r2, 0x00000005, \
    bsr test_2_sub; \
    nop; \
    mov r1, r2; \
    bra test_2_done; \
    nop; \
  test_2_sub: \
    sts pr, r3; \
    mov #5, r1; \
    rts; \
    nop; \
  test_2_done: \
    nop; \
  )

  /* Test sts pr after lds */
  TEST_CASE( 3, r3, 0xabcd1234, \
    mov.l test_3_val, r1; \
    lds r1, pr; \
    sts pr, r3; \
    bra 3f; \
    nop; \
    .align 2; \
  test_3_val: \
    .long 0xabcd1234; \
  3: \
  )

  /* Test sts pr multiple times */
  TEST_CASE( 4, r4, 0x12345678, \
    mov.l test_4_val, r1; \
    lds r1, pr; \
    sts pr, r2; \
    sts pr, r3; \
    sts pr, r4; \
    bra 3f; \
    nop; \
    .align 2; \
  test_4_val: \
    .long 0x12345678; \
  3: \
  )

  /* Test sts pr preservation */
  TEST_CASE( 5, r3, 0x5a5a5a5a, \
    mov.l test_5_val, r1; \
    lds r1, pr; \
    mov #10, r2; \
    add r2, r2; \
    sts pr, r3; \
    bra 3f; \
    nop; \
    .align 2; \
  test_5_val: \
    .long 0x5a5a5a5a; \
  3: \
  )

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
