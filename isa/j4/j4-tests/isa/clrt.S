/* j2 (SuperH-2) CLRT instruction tests */
/* CLRT clears the T bit */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * T-bit control tests - Clear T
   *-------------------------------------------------------------*/

  /* Test clrt when T=1 */
  TEST_CASE( 2, r2, 0x00000000, \
    sett; \
    clrt; \
    movt r2; \
  )

  /* Test clrt when T=0 */
  TEST_CASE( 3, r2, 0x00000000, \
    clrt; \
    clrt; \
    movt r2; \
  )

  /* Test multiple clrt */
  TEST_CASE( 4, r2, 0x00000000, \
    sett; \
    clrt; \
    clrt; \
    clrt; \
    movt r2; \
  )

  /* Test clrt after comparison */
  TEST_CASE( 5, r2, 0x00000000, \
    mov #5, r1; \
    mov #5, r3; \
    cmp/eq r1, r3; \
    clrt; \
    movt r2; \
  )

  /* Test clrt persistence */
  TEST_CASE( 6, r3, 0x00000000, \
    clrt; \
    mov #10, r1; \
    mov #20, r2; \
    movt r3; \
  )

  TEST_PASSFAIL

J2TEST_CODE_END

J2TEST_PASS
J2TEST_FAIL

J2TEST_DATA_BEGIN
  TEST_DATA
J2TEST_DATA_END
