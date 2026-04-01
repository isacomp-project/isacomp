/* j2 (SuperH-2) SETT instruction tests */
/* SETT sets the T bit */

#include "test_macros.h"

J2TEST_CODE_BEGIN

  /*-------------------------------------------------------------
   * T-bit control tests - Set T
   *-------------------------------------------------------------*/

  /* Test sett when T=0 */
  TEST_CASE( 2, r2, 0x00000001, \
    clrt; \
    sett; \
    movt r2; \
  )

  /* Test sett when T=1 */
  TEST_CASE( 3, r2, 0x00000001, \
    sett; \
    sett; \
    movt r2; \
  )

  /* Test multiple sett */
  TEST_CASE( 4, r2, 0x00000001, \
    clrt; \
    sett; \
    sett; \
    sett; \
    movt r2; \
  )

  /* Test sett after failed comparison */
  TEST_CASE( 5, r2, 0x00000001, \
    mov #5, r1; \
    mov #6, r3; \
    cmp/eq r1, r3; \
    sett; \
    movt r2; \
  )

  /* Test sett persistence */
  TEST_CASE( 6, r3, 0x00000001, \
    sett; \
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
