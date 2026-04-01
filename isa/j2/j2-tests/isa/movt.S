/* j2 (SuperH-2) MOVT instruction tests */
/* MOVT moves T bit value to register */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * T-bit move tests
   *-------------------------------------------------------------*/

  /* Test movt when T=1 */
  TEST_CASE( 2, r2, 0x00000001, \
    sett; \
    movt r2; \
  )

  /* Test movt when T=0 */
  TEST_CASE( 3, r2, 0x00000000, \
    clrt; \
    movt r2; \
  )

  /* Test movt after comparison true */
  TEST_CASE( 4, r2, 0x00000001, \
    mov #7, r1; \
    mov #7, r3; \
    cmp/eq r1, r3; \
    movt r2; \
  )

  /* Test movt after comparison false */
  TEST_CASE( 5, r2, 0x00000000, \
    mov #5, r1; \
    mov #6, r3; \
    cmp/eq r1, r3; \
    movt r2; \
  )

  /* Test movt multiple times with same T */
  TEST_CASE( 6, r3, 0x00000001, \
    sett; \
    movt r1; \
    movt r2; \
    movt r3; \
  )

  /* Test movt doesn't change T */
  TEST_CASE( 7, r3, 0x00000001, \
    sett; \
    movt r1; \
    movt r2; \
    movt r3; \
  )

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
