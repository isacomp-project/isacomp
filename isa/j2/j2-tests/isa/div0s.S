/* j2 (SuperH-2) DIV0S instruction tests */
/* DIV0S initializes division (signed) - sets Q, M, T bits */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Division step 0 tests - Signed division initialization
   *-------------------------------------------------------------*/

  /* Test div0s with positive/positive (M=0, Q=0, T=0) */
  TEST_CASE( 2, r3, 0x00000000, \
    mov #5, r1; \
    mov #3, r2; \
    div0s r2, r1; \
    movt r3; \
  )

  /* Test div0s with positive/negative (different signs, T=1) */
  TEST_CASE( 3, r3, 0x00000001, \
    mov #5, r1; \
    mov #-3, r2; \
    div0s r2, r1; \
    movt r3; \
  )

  /* Test div0s with negative/positive (different signs, T=1) */
  TEST_CASE( 4, r3, 0x00000001, \
    mov #-5, r1; \
    mov #3, r2; \
    div0s r2, r1; \
    movt r3; \
  )

  /* Test div0s with negative/negative (same signs, T=0) */
  TEST_CASE( 5, r3, 0x00000000, \
    mov #-5, r1; \
    mov #-3, r2; \
    div0s r2, r1; \
    movt r3; \
  )

  /* Test div0s with zero dividend */
  TEST_CASE( 6, r3, 0x00000000, \
    mov #0, r1; \
    mov #5, r2; \
    div0s r2, r1; \
    movt r3; \
  )

  /* Test div0s with zero divisor */
  TEST_CASE( 7, r3, 0x00000000, \
    mov #5, r1; \
    mov #0, r2; \
    div0s r2, r1; \
    movt r3; \
  )

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
