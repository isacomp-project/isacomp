/* j2 (SuperH-2) CMP/EQ instruction tests */
/* CMP/EQ Rm, Rn - sets T=1 if Rn == Rm, else T=0 */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Equality comparison tests
   *-------------------------------------------------------------*/

  /* 0 == 0: should set T, then BT should branch */
  TEST_CASE( 2, r3, 0x00000001, \
    mov #0, r1; \
    mov #0, r2; \
    cmp/eq r1, r2; \
    movt r3; \
  )

  /* 1 == 1: should set T */
  TEST_CASE( 3, r3, 0x00000001, \
    mov #1, r1; \
    mov #1, r2; \
    cmp/eq r1, r2; \
    movt r3; \
  )

  /* 1 == 0: should clear T */
  TEST_CASE( 4, r3, 0x00000000, \
    mov #1, r1; \
    mov #0, r2; \
    cmp/eq r1, r2; \
    movt r3; \
  )

  /* 0 == 1: should clear T */
  TEST_CASE( 5, r3, 0x00000000, \
    mov #0, r1; \
    mov #1, r2; \
    cmp/eq r1, r2; \
    movt r3; \
  )

  /* -1 == -1: should set T */
  TEST_CASE( 6, r3, 0x00000001, \
    mov #-1, r1; \
    mov #-1, r2; \
    cmp/eq r1, r2; \
    movt r3; \
  )

  /* 5 == -5: should clear T */
  TEST_CASE( 7, r3, 0x00000000, \
    mov #5, r1; \
    mov #-5, r2; \
    cmp/eq r1, r2; \
    movt r3; \
  )

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
