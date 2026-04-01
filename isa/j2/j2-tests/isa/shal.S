/* j2 (SuperH-2) SHAL instruction tests */
/* SHAL shifts arithmetic left by 1 bit, MSB goes to T */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Shift arithmetic left tests
   *-------------------------------------------------------------*/

  /* Test shal basic */
  TEST_CASE( 2, r1, 0x00000002, \
    mov #1, r1; \
    shal r1; \
  )

  /* Test shal zero */
  TEST_CASE( 3, r1, 0x00000000, \
    mov #0, r1; \
    shal r1; \
  )

  /* Test shal with MSB=1 sets T */
  TEST_CASE( 4, r2, 0x00000001, \
    mov.l test_4_val, r1; \
    shal r1; \
    movt r2; \
    bra 3f; \
    nop; \
    .align 2; \
  test_4_val: \
    .long 0x80000000; \
  3: \
  )

  /* Test shal with MSB=0 clears T */
  TEST_CASE( 5, r2, 0x00000000, \
    mov #1, r1; \
    shal r1; \
    movt r2; \
  )

  /* Test shal negative value */
  TEST_CASE( 6, r1, 0xfffffffe, \
    mov #-1, r1; \
    shal r1; \
  )

  /* Test shal multiple times */
  TEST_CASE( 7, r1, 0x00000008, \
    mov #1, r1; \
    shal r1; \
    shal r1; \
    shal r1; \
  )

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
