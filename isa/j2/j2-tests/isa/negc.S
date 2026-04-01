/* j2 (SuperH-2) NEGC instruction tests */
/* NEGC negates with borrow from T bit */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * Arithmetic tests - Negate with carry
   *-------------------------------------------------------------*/

  /* negc 0 with T=0 = 0 */
  TEST_CASE( 2, r2, 0x00000000, \
    clrt; \
    mov #0, r1; \
    negc r1, r2; \
  )

  /* negc 0 with T=1 = 0xffffffff */
  TEST_CASE( 3, r2, 0xffffffff, \
    sett; \
    mov #0, r1; \
    negc r1, r2; \
  )

  /* negc 1 with T=0 = 0xffffffff */
  TEST_CASE( 4, r2, 0xffffffff, \
    clrt; \
    mov #1, r1; \
    negc r1, r2; \
  )

  /* negc 1 with T=1 = 0xfffffffe */
  TEST_CASE( 5, r2, 0xfffffffe, \
    sett; \
    mov #1, r1; \
    negc r1, r2; \
  )

  /* negc -1 with T=0 = 1 */
  TEST_CASE( 6, r2, 0x00000001, \
    clrt; \
    mov #-1, r1; \
    negc r1, r2; \
  )

  /* negc -1 with T=1 = 0 */
  TEST_CASE( 7, r2, 0x00000000, \
    sett; \
    mov #-1, r1; \
    negc r1, r2; \
  )

  /* negc 5 with T=1 = -6 */
  TEST_CASE( 8, r2, 0xfffffffa, \
    sett; \
    mov #5, r1; \
    negc r1, r2; \
  )

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
